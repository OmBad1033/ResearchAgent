// Mock event emitter — replays the sequence from
// frontend_plan.md §"Build a mock that matches the contract exactly".
//
// Every event below is shaped EXACTLY per contract.md §"Event schema".
// Do not deviate — at merge time this file is swapped for the real WS
// connection, and any drift here will silently propagate.

import type { WsEvent } from '../types';

type ScheduledEvent = { event: WsEvent; delayMs: number };

// Helper that advances the virtual clock and returns a fresh ISO timestamp.
// The MockRunner uses these per-event delays so the timing variation
// (e.g. 900ms deep_dive, 700ms worth_it) actually plays out — that's the
// whole point of rehearsing against the mock.
function makeTimeline() {
  let t = 0;
  return {
    now: () => new Date(0).toISOString(),
    step: (ms: number) => {
      t += ms;
      return new Date(t).toISOString();
    },
  };
}

export function buildMockSequence(): ScheduledEvent[] {
  const out: ScheduledEvent[] = [];
  const tl = makeTimeline();
  const push = (event: WsEvent, delayMs: number) => {
    out.push({ event, delayMs });
  };
  const emit = (event: Omit<WsEvent, 'timestamp'>, delayMs: number) => {
    push({ ...event, timestamp: tl.step(delayMs) } as WsEvent, delayMs);
  };

  // 1. Static nodes added at run start
  emit({ type: 'node_added', run_id: 'mock', node_id: 'manager', node_type: 'manager', parent_id: null, label: 'manager', opportunity_id: null }, 0);
  emit({ type: 'node_added', run_id: 'mock', node_id: 'opportunity_discovery', node_type: 'opportunity_discovery', parent_id: 'manager', label: 'opportunity_discovery', opportunity_id: null }, 0);
  emit({ type: 'node_added', run_id: 'mock', node_id: 'approval_router', node_type: 'approval_router', parent_id: 'manager', label: 'approval_router', opportunity_id: null }, 0);
  emit({ type: 'node_added', run_id: 'mock', node_id: 'ai_approval', node_type: 'ai_approval', parent_id: 'approval_router', label: 'ai_approval', opportunity_id: null }, 0);
  emit({ type: 'node_added', run_id: 'mock', node_id: 'orchestration', node_type: 'orchestration', parent_id: 'manager', label: 'orchestration', opportunity_id: null }, 0);
  emit({ type: 'node_added', run_id: 'mock', node_id: 'synthesis', node_type: 'synthesis', parent_id: 'manager', label: 'synthesis', opportunity_id: null }, 0);

  // 2. Manager → opportunity_discovery
  emit({ type: 'node_status', run_id: 'mock', node_id: 'manager', status: 'running', summary: 'planning next step' }, 50);
  emit({ type: 'edge_active', run_id: 'mock', from: 'manager', to: 'opportunity_discovery' }, 10);
  emit({ type: 'node_status', run_id: 'mock', node_id: 'opportunity_discovery', status: 'running', summary: 'searching the web' }, 20);
  emit({ type: 'node_status', run_id: 'mock', node_id: 'opportunity_discovery', status: 'completed', summary: 'found 3 opportunities' }, 800);
  emit({ type: 'node_status', run_id: 'mock', node_id: 'manager', status: 'completed', summary: null }, 10);

  // 3. Manager → approval_router → ai_approval
  emit({ type: 'node_status', run_id: 'mock', node_id: 'manager', status: 'running', summary: 'planning next step' }, 100);
  emit({ type: 'edge_active', run_id: 'mock', from: 'manager', to: 'approval_router' }, 10);
  emit({ type: 'node_status', run_id: 'mock', node_id: 'approval_router', status: 'running', summary: 'routing approval' }, 20);
  emit({ type: 'node_status', run_id: 'mock', node_id: 'approval_router', status: 'completed', summary: null }, 50);
  emit({ type: 'edge_active', run_id: 'mock', from: 'approval_router', to: 'ai_approval' }, 10);
  emit({ type: 'node_status', run_id: 'mock', node_id: 'ai_approval', status: 'running', summary: 'reviewing opportunities' }, 20);
  emit({ type: 'node_status', run_id: 'mock', node_id: 'ai_approval', status: 'completed', summary: 'approved opp_1, opp_2, opp_3' }, 600);
  emit({ type: 'node_status', run_id: 'mock', node_id: 'manager', status: 'completed', summary: null }, 10);

  // 4. Dynamic deep_dive fan-out — 3 in parallel (the key case for dagre)
  emit({ type: 'node_status', run_id: 'mock', node_id: 'manager', status: 'running', summary: 'planning next step' }, 100);
  emit({ type: 'edge_active', run_id: 'mock', from: 'manager', to: 'deep_dive_opp_1' }, 10);
  emit({ type: 'edge_active', run_id: 'mock', from: 'manager', to: 'deep_dive_opp_2' }, 5);
  emit({ type: 'edge_active', run_id: 'mock', from: 'manager', to: 'deep_dive_opp_3' }, 5);

  for (const opp of ['opp_1', 'opp_2', 'opp_3']) {
    emit({
      type: 'node_added', run_id: 'mock', node_id: `deep_dive_${opp}`, node_type: 'deep_dive_subagent',
      parent_id: 'manager', label: `deep_dive ${opp}`, opportunity_id: opp,
    }, 10);
  }
  for (const opp of ['opp_1', 'opp_2', 'opp_3']) {
    emit({ type: 'node_status', run_id: 'mock', node_id: `deep_dive_${opp}`, status: 'running', summary: 'researching existing solutions' }, 20);
  }
  emit({ type: 'node_status', run_id: 'mock', node_id: 'deep_dive_opp_1', status: 'completed', summary: 'no direct competitor' }, 900);
  emit({ type: 'node_status', run_id: 'mock', node_id: 'deep_dive_opp_2', status: 'completed', summary: 'some indirect solutions' }, 400);
  emit({ type: 'node_status', run_id: 'mock', node_id: 'deep_dive_opp_3', status: 'completed', summary: 'crowded space' }, 600);
  emit({ type: 'node_status', run_id: 'mock', node_id: 'manager', status: 'completed', summary: null }, 10);

  // 5. Orchestration fan-in (near-instantaneous, per backend spec)
  emit({ type: 'node_status', run_id: 'mock', node_id: 'manager', status: 'running', summary: 'planning next step' }, 50);
  emit({ type: 'edge_active', run_id: 'mock', from: 'manager', to: 'orchestration' }, 5);
  emit({ type: 'node_status', run_id: 'mock', node_id: 'orchestration', status: 'running', summary: 'joining results' }, 5);
  emit({ type: 'node_status', run_id: 'mock', node_id: 'orchestration', status: 'completed', summary: null }, 40);
  emit({ type: 'node_status', run_id: 'mock', node_id: 'manager', status: 'completed', summary: null }, 10);

  // 6. Dynamic worth_it fan-out — 3 in parallel
  emit({ type: 'node_status', run_id: 'mock', node_id: 'manager', status: 'running', summary: 'planning next step' }, 80);
  emit({ type: 'edge_active', run_id: 'mock', from: 'manager', to: 'worth_it_opp_1' }, 10);
  emit({ type: 'edge_active', run_id: 'mock', from: 'manager', to: 'worth_it_opp_2' }, 5);
  emit({ type: 'edge_active', run_id: 'mock', from: 'manager', to: 'worth_it_opp_3' }, 5);
  for (const opp of ['opp_1', 'opp_2', 'opp_3']) {
    emit({
      type: 'node_added', run_id: 'mock', node_id: `worth_it_${opp}`, node_type: 'worth_it_subagent',
      parent_id: 'manager', label: `worth_it ${opp}`, opportunity_id: opp,
    }, 10);
  }
  for (const opp of ['opp_1', 'opp_2', 'opp_3']) {
    emit({ type: 'node_status', run_id: 'mock', node_id: `worth_it_${opp}`, status: 'running', summary: 'evaluating viability' }, 20);
  }
  emit({ type: 'node_status', run_id: 'mock', node_id: 'worth_it_opp_1', status: 'completed', summary: 'verdict: pursue' }, 700);
  emit({ type: 'node_status', run_id: 'mock', node_id: 'worth_it_opp_2', status: 'completed', summary: 'verdict: skip' }, 400);
  emit({ type: 'node_status', run_id: 'mock', node_id: 'worth_it_opp_3', status: 'completed', summary: 'verdict: pursue' }, 500);
  emit({ type: 'node_status', run_id: 'mock', node_id: 'manager', status: 'completed', summary: null }, 10);

  // 7. synthesis → run_completed
  emit({ type: 'node_status', run_id: 'mock', node_id: 'manager', status: 'running', summary: 'planning next step' }, 50);
  emit({ type: 'edge_active', run_id: 'mock', from: 'manager', to: 'synthesis' }, 10);
  emit({ type: 'node_status', run_id: 'mock', node_id: 'synthesis', status: 'running', summary: 'writing report' }, 20);
  emit({ type: 'node_status', run_id: 'mock', node_id: 'synthesis', status: 'completed', summary: 'report ready' }, 800);
  emit({ type: 'node_status', run_id: 'mock', node_id: 'manager', status: 'completed', summary: null }, 10);
  emit({ type: 'run_completed', run_id: 'mock' }, 50);

  return out;
}
