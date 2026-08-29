"""
EventWriter — per-run pub/sub used by the FastAPI bridge.

The runner reads events from LangGraph's custom stream and pushes each
one to the EventWriter for a given run_id. WebSocket handlers subscribe
to that EventWriter and forward events to the client as they arrive.

Design:
- One EventWriter per active run_id, kept in a module-level registry.
- WebSocket handlers `await writer.subscribe()` to get an asyncio.Queue
  of events from the moment of subscription onwards.
- Late subscribers do NOT get historical events — that's a frontend
  concern (the React UI buffers them itself, or refreshes after the
  run completes by fetching history).
- On run completion (or terminal error), the writer is closed; all
  subscribers' queues receive a `None` sentinel and unsubscribe.

Why an asyncio.Queue and not a broadcast callback:
- The frontend is a single WebSocket per run; we don't need multicast.
- A queue lets `await queue.get()` naturally backpressure slow clients.
"""

from __future__ import annotations

import asyncio
from typing import Any, AsyncIterator


class EventWriter:
    """Per-run event stream.

    Created by the runner when a run starts, deleted from the registry
    when the run completes or errors. The WebSocket handler holds a
    reference to the same instance for the lifetime of its connection.
    """

    def __init__(self, run_id: str) -> None:
        self.run_id = run_id
        self._subscribers: list[asyncio.Queue[dict[str, Any] | None]] = []
        self._closed = False
        # Buffer events emitted before the first subscriber arrives.
        # The runner pushes 7 node_added events for static nodes up
        # front; the WS handler subscribes shortly after start_run()
        # spawns the runner task, but there's an asyncio race where
        # the runner's pushes can land before the handler's
        # subscribe() registers its queue. Without buffering, those
        # early events are lost.
        self._early_events: list[dict[str, Any]] = []
        self._early_event_limit = 64

    def emit(self, event: dict[str, Any]) -> None:
        """Push an event to every subscriber. Non-blocking — drops the
        event for any subscriber whose queue is full (a slow client
        should not stall LangGraph execution).

        If no subscriber is registered yet, buffer the event (up to
        `_early_event_limit`) so late subscribers don't miss the
        static-node announcement. Once a subscriber arrives, all
        buffered events are flushed into its queue in order.
        """
        if not self._subscribers:
            if len(self._early_events) < self._early_event_limit:
                self._early_events.append(event)
            return
        for q in self._subscribers:
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                # Slow client: best-effort drop. The frontend can re-fetch
                # history after the run completes if it missed events.
                pass

    async def subscribe(self, maxsize: int = 256) -> AsyncIterator[dict[str, Any]]:
        """Async iterator that yields events until the run closes.

        Yields each event as it arrives. When the writer is closed,
        raises StopAsyncIteration so the consumer's `async for` exits
        cleanly.

        Any events that were pushed before this subscriber existed
        (buffered in `_early_events`) are yielded first so the
        subscriber sees the full event sequence.
        """
        queue: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue(maxsize=maxsize)
        self._subscribers.append(queue)
        # Drain the pre-subscriber buffer into our queue. We swap the
        # list atomically (no other subscriber can be appending here
        # since we're sync and no emit() runs between the append and
        # the drain in this event loop slice).
        early, self._early_events = self._early_events, []
        for ev in early:
            try:
                queue.put_nowait(ev)
            except asyncio.QueueFull:
                pass
        try:
            while True:
                item = await queue.get()
                if item is None:
                    return
                yield item
        finally:
            # Idempotent removal — guard against double-unsubscribe.
            try:
                self._subscribers.remove(queue)
            except ValueError:
                pass

    def close(self) -> None:
        """Mark the writer as closed and unblock every subscriber with
        a `None` sentinel."""
        if self._closed:
            return
        self._closed = True
        for q in self._subscribers:
            try:
                q.put_nowait(None)
            except asyncio.QueueFull:
                # Force-drain a slot so the sentinel lands.
                try:
                    _ = q.get_nowait()
                except asyncio.QueueEmpty:
                    pass
                try:
                    q.put_nowait(None)
                except asyncio.QueueFull:
                    pass


# Module-level registry: run_id -> EventWriter. The runner registers
# when a run starts, the WebSocket handler looks up by run_id, the
# runner deregisters when the run ends. Synchronous accessor — both
# runner and handler run on the same event loop so no locking is needed.
_registry: dict[str, EventWriter] = {}


def register_writer(writer: EventWriter) -> None:
    """Add a writer to the registry. Overwrites any existing writer for
    the same run_id (last-writer-wins) so a buggy re-run doesn't strand
    a stale writer."""
    _registry[writer.run_id] = writer


def get_writer(run_id: str) -> EventWriter | None:
    """Look up a writer by run_id. Returns None if no run is active."""
    return _registry.get(run_id)


def unregister_writer(run_id: str) -> None:
    """Remove a writer from the registry. Idempotent."""
    _registry.pop(run_id, None)
