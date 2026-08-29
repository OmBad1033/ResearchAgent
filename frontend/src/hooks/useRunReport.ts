// useRunReport — fetches the synthesis report from
// GET /runs/{runId}/report per contract.md §"REST: run report".
//
// Supports manual refetch and a polling option for the case where the
// caller wants to wait until synthesis completes (returns 404 → keep
// polling; returns 200 → resolve).

import { useCallback, useEffect, useRef, useState } from 'react';
import type { RunReport } from '../types';

const REPORT_URL = (runId: string) => `http://localhost:8000/runs/${runId}/report`;

export type UseRunReportOptions = {
  /** When true, polls until the endpoint returns 200 or abort is signalled. */
  pollUntilReady?: boolean;
  /** Poll interval in ms (default 1500). Only used when pollUntilReady is true. */
  pollIntervalMs?: number;
};

export type RunReportState = {
  data: RunReport | null;
  loading: boolean;
  notReady: boolean;
  error: string | null;
  refetch: () => void;
};

export function useRunReport(runId: string, options: UseRunReportOptions = {}): RunReportState {
  const [data, setData] = useState<RunReport | null>(null);
  const [loading, setLoading] = useState(false);
  const [notReady, setNotReady] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [tick, setTick] = useState(0);
  const pollAbortRef = useRef<AbortController | null>(null);

  const refetch = useCallback(() => setTick((t) => t + 1), []);

  useEffect(() => {
    pollAbortRef.current?.abort();
    if (!runId) return;
    const controller = new AbortController();
    pollAbortRef.current = controller;
    let cancelled = false;

    const fetchOnce = async (): Promise<RunReport | 'not-ready' | null> => {
      try {
        const res = await fetch(REPORT_URL(runId), { signal: controller.signal });
        if (res.status === 404) return 'not-ready';
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        return (await res.json()) as RunReport;
      } catch (err) {
        if ((err as Error).name === 'AbortError') return null;
        throw err;
      }
    };

    const run = async () => {
      setLoading(true);
      setError(null);
      try {
        if (options.pollUntilReady) {
          setNotReady(false);
          while (!cancelled) {
            const result = await fetchOnce();
            if (cancelled) return;
            if (result === 'not-ready') {
              setNotReady(true);
              await new Promise((r) => setTimeout(r, options.pollIntervalMs ?? 1500));
              continue;
            }
            if (result === null) return; // aborted mid-flight
            setData(result);
            setNotReady(false);
            return;
          }
        } else {
          const result = await fetchOnce();
          if (cancelled) return;
          if (result === 'not-ready') {
            setNotReady(true);
            setData(null);
            return;
          }
          if (result === null) return;
          setData(result);
          setNotReady(false);
        }
      } catch (err) {
        if (!cancelled) setError((err as Error).message);
      } finally {
        if (!cancelled) setLoading(false);
      }
    };

    void run();

    return () => {
      cancelled = true;
      controller.abort();
    };
  }, [runId, tick, options.pollUntilReady, options.pollIntervalMs]);

  return { data, loading, notReady, error, refetch };
}
