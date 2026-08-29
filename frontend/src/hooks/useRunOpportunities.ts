// useRunOpportunities — fetches the discovered opportunities for a run
// from GET /runs/{runId}/opportunities. Used by the approval UI in
// HistoryDrawer to render checkboxes while the run is paused at
// human_approval.
//
// Returns { data, loading, error, refetch } so the drawer can show
// a loading state and recover from network errors.

import { useCallback, useEffect, useState } from 'react';
import type { RunOpportunities } from '../types';

const URL = (runId: string) => `http://localhost:8000/runs/${runId}/opportunities`;

export type RunOpportunitiesState = {
  data: RunOpportunities | null;
  loading: boolean;
  error: string | null;
  refetch: () => void;
};

export function useRunOpportunities(runId: string, enabled: boolean): RunOpportunitiesState {
  const [data, setData] = useState<RunOpportunities | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [tick, setTick] = useState(0);

  const refetch = useCallback(() => setTick((t) => t + 1), []);

  useEffect(() => {
    if (!enabled) {
      setData(null);
      setError(null);
      return;
    }
    let cancelled = false;
    setLoading(true);
    setError(null);

    fetch(URL(runId))
      .then(async (res) => {
        if (!res.ok) throw new Error(`HTTP ${res.status}`);
        return (await res.json()) as RunOpportunities;
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
  }, [runId, enabled, tick]);

  return { data, loading, error, refetch };
}