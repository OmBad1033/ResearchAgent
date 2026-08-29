// useNodeHistory — fetches the per-node history from the REST endpoint
// documented at contract.md §"REST: node history".
//
// Returns { data, loading, error, refetch } so the HistoryDrawer can show
// a loading skeleton and recover from a 404 cleanly.

import { useCallback, useEffect, useState } from 'react';
import type { NodeHistory } from '../types';

const HISTORY_URL = (runId: string, nodeId: string) =>
  `http://localhost:8000/runs/${runId}/nodes/${nodeId}/history`;

export type NodeHistoryState = {
  data: NodeHistory | null;
  loading: boolean;
  error: string | null;
  refetch: () => void;
};

export function useNodeHistory(runId: string, nodeId: string | null): NodeHistoryState {
  const [data, setData] = useState<NodeHistory | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [tick, setTick] = useState(0);

  const refetch = useCallback(() => setTick((t) => t + 1), []);

  useEffect(() => {
    if (!nodeId) {
      setData(null);
      setError(null);
      return;
    }
    let cancelled = false;
    setLoading(true);
    setError(null);

    fetch(HISTORY_URL(runId, nodeId))
      .then(async (res) => {
        if (!res.ok) {
          throw new Error(`HTTP ${res.status}`);
        }
        return (await res.json()) as NodeHistory;
      })
      .then((json) => {
        if (cancelled) return;
        setData(json);
      })
      .catch((err: Error) => {
        if (cancelled) return;
        setError(err.message);
        setData(null);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [runId, nodeId, tick]);

  return { data, loading, error, refetch };
}
