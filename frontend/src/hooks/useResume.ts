// useResume — POST /runs/{runId}/resume with the chosen opportunity ids.
//
// Returns a stable `resume(ids)` function plus submitting/error state
// for the approval UI to disable buttons while in flight.

import { useCallback, useState } from 'react';

const URL = (runId: string) => `http://localhost:8000/runs/${runId}/resume`;

export type UseResumeResult = {
  resume: (approvedOpportunityIds: string[]) => Promise<boolean>;
  submitting: boolean;
  error: string | null;
};

export function useResume(runId: string): UseResumeResult {
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const resume = useCallback(
    async (approvedOpportunityIds: string[]): Promise<boolean> => {
      setSubmitting(true);
      setError(null);
      try {
        const res = await fetch(URL(runId), {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ approved_opportunity_ids: approvedOpportunityIds }),
        });
        if (res.status !== 200 && res.status !== 202) {
          throw new Error(`HTTP ${res.status}`);
        }
        return true;
      } catch (err) {
        setError((err as Error).message);
        return false;
      } finally {
        setSubmitting(false);
      }
    },
    [runId],
  );

  return { resume, submitting, error };
}