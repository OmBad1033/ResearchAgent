// useSolutionDesign — asks the Architect Agent (A2A, via the backend
// proxy) for a solution design for one opportunity node.
//
// POST /runs/{runId}/nodes/{nodeId}/design → 200 { design: SolutionDesign }
// Backend maps failures: 404 = no opportunity for this node, 502 =
// Architect unreachable / failed task. Both surface as `error` here.
//
// Unlike the GET hooks, this is POST-on-demand: nothing fires until the
// caller invokes `requestDesign()`. Returns { design, requesting, error,
// requestDesign, reset } so the drawer can render button → spinner →
// result inline.

import { useCallback, useEffect, useRef, useState } from 'react';
import type { NodeDesignResponse, SolutionDesign } from '../types';

const DESIGN_URL = (runId: string, nodeId: string) =>
  `http://localhost:8000/runs/${runId}/nodes/${nodeId}/design`;

export type UseSolutionDesignResult = {
  design: SolutionDesign | null;
  requesting: boolean;
  error: string | null;
  requestDesign: () => void;
  reset: () => void;
};

export function useSolutionDesign(runId: string, nodeId: string | null): UseSolutionDesignResult {
  const [design, setDesign] = useState<SolutionDesign | null>(null);
  const [requesting, setRequesting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);

  const reset = useCallback(() => {
    abortRef.current?.abort();
    setDesign(null);
    setError(null);
    setRequesting(false);
  }, []);

  // Fresh node → clear the previous design. (Previous design belongs to
  // a different opportunity; never show it under the new node id.)
  useEffect(() => {
    reset();
  }, [runId, nodeId, reset]);

  const requestDesign = useCallback(() => {
    if (!nodeId || requesting) return;
    abortRef.current?.abort();
    const controller = new AbortController();
    abortRef.current = controller;
    setRequesting(true);
    setError(null);

    fetch(DESIGN_URL(runId, nodeId), {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({}),
      signal: controller.signal,
    })
      .then(async (res) => {
        if (!res.ok) {
          // Backend returns JSON { detail } on 404/502 — surface it.
          let detail = `HTTP ${res.status}`;
          try {
            const errBody = (await res.json()) as { detail?: string };
            if (errBody.detail) detail = errBody.detail;
          } catch {
            // Non-JSON error body — keep the HTTP status.
          }
          throw new Error(detail);
        }
        return (await res.json()) as NodeDesignResponse;
      })
      .then((json) => {
        setDesign(json.design);
      })
      .catch((err: Error) => {
        if (err.name === 'AbortError') return;
        setError(err.message);
        setDesign(null);
      })
      .finally(() => {
        setRequesting(false);
      });
  }, [runId, nodeId, requesting]);

  // Unmount / node switch mid-flight → cancel the fetch.
  useEffect(() => {
    return () => {
      abortRef.current?.abort();
    };
  }, []);

  return { design, requesting, error, requestDesign, reset };
}
