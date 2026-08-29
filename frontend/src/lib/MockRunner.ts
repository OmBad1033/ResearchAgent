// MockRunner — plays a canned sequence of events into a sink (typically the
// graphStore's applyEvent). Uses cumulative scheduling so timing variation in
// the sequence actually plays out (the whole point of rehearsing).

import { buildMockSequence } from './mockEmitter';
import type { WsEvent } from '../types';

export type EventSink = (event: WsEvent) => void;

export class MockRunner {
  private timers: ReturnType<typeof setTimeout>[] = [];
  private cancelled = false;

  start(sink: EventSink): void {
    this.stop();
    this.cancelled = false;
    const sequence = buildMockSequence();
    let elapsed = 0;
    for (const { event, delayMs } of sequence) {
      elapsed += delayMs;
      const timer = setTimeout(() => {
        if (this.cancelled) return;
        sink(event);
      }, elapsed);
      this.timers.push(timer);
    }
  }

  stop(): void {
    this.cancelled = true;
    for (const t of this.timers) clearTimeout(t);
    this.timers = [];
  }
}
