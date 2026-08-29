// useGraphSocket — single entry point for the graph event stream.
//
// Switches between mock and real WebSocket based on:
//   1. VITE_USE_MOCK=true (env), OR
//   2. ?mock=true in the URL query string
//
// Takes `params: RunParams | null` so the connection only opens once the
// user has filled in the input modal. When `params` is null the hook is
// inert (no connection, no mock).
//
// At merge time, the only change needed is: remove the env/query override
// OR set the real WS URL below. Everything downstream is contract-shaped.

import { useEffect, useRef } from 'react';
import { useGraphStore } from '../store/graphStore';
import { MockRunner } from '../lib/MockRunner';
import type { RunParams, WsEvent } from '../types';

const REAL_WS_URL = (runId: string) => `ws://localhost:8000/ws/${runId}`;

function shouldUseMock(): boolean {
  if (import.meta.env.VITE_USE_MOCK === 'true') return true;
  if (typeof window !== 'undefined') {
    const params = new URLSearchParams(window.location.search);
    if (params.get('mock') === 'true') return true;
  }
  return false;
}

// Strip undefined keys so we don't send `"report_focus": undefined` etc.
function sessionStartFrame(params: RunParams): Record<string, unknown> {
  const frame: Record<string, unknown> = {
    domain: params.domain,
    hitl_mode: params.hitlMode,
  };
  if (params.reportFocus && params.reportFocus.trim() !== '') {
    frame.report_focus = params.reportFocus;
  }
  if (typeof params.maxOpportunities === 'number' && Number.isFinite(params.maxOpportunities)) {
    frame.max_opportunities = params.maxOpportunities;
  }
  return frame;
}

export function useGraphSocket(runId: string, params: RunParams | null): void {
  const applyEvent = useGraphStore((s) => s.applyEvent);
  const reset = useGraphStore((s) => s.reset);
  const wsRef = useRef<WebSocket | null>(null);
  const mockRef = useRef<MockRunner | null>(null);

  useEffect(() => {
    if (!params) return; // inert until the user submits the form

    reset();

    if (shouldUseMock()) {
      const runner = new MockRunner();
      mockRef.current = runner;
      runner.start((event: WsEvent) => applyEvent(event));
      return () => runner.stop();
    }

    const url = REAL_WS_URL(runId);

    // Single shared abort signal — when this effect unmounts (StrictMode
    // double-invocation, params transition, or run reset) the signal
    // flips and `ws.send()` becomes a no-op. This prevents a stale
    // CONNECTING socket from sending the start frame and triggering
    // `/ws/{run_id}` server-side work that the server then has to
    // garbage-collect when we close it.
    const abort = new AbortController();
    let ws: WebSocket | null = null;
    try {
      ws = new WebSocket(url);
    } catch (err) {
      // eslint-disable-next-line no-console
      console.error('Failed to open WebSocket', err);
      return;
    }
    wsRef.current = ws;

    ws.onopen = () => {
      if (abort.signal.aborted) {
        try { ws?.close(); } catch { /* ignore */ }
        return;
      }
      try {
        ws?.send(JSON.stringify(sessionStartFrame(params)));
      } catch (err) {
        // eslint-disable-next-line no-console
        console.error('Failed to send WS start frame', err);
      }
    };

    ws.onmessage = (msg) => {
      if (abort.signal.aborted) return;
      try {
        const event = JSON.parse(msg.data) as WsEvent;
        applyEvent(event);
      } catch (err) {
        // eslint-disable-next-line no-console
        console.error('Failed to parse WS message', err, msg.data);
      }
    };

    ws.onerror = (err) => {
      // eslint-disable-next-line no-console
      console.error('WebSocket error', err);
    };

    return () => {
      abort.abort();
      try { ws?.close(); } catch { /* ignore */ }
      wsRef.current = null;
    };
    // applyEvent and reset come from a stable zustand selector — they
    // are stable across renders and don't need to be in deps.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [runId, params]);
}
