// Shared event types — mirrors contract.md §"Event schema" verbatim.

export type AgentNodeType =
  | 'manager'
  | 'opportunity_discovery'
  | 'approval_router'
  | 'human_approval'
  | 'ai_approval'
  | 'deep_dive_subagent'
  | 'orchestration'
  | 'worth_it_subagent'
  | 'synthesis';

export type NodeStatus = 'idle' | 'running' | 'completed' | 'error';

export type HitlMode = 'human' | 'ai';

// Run params — sent as the session-start frame per contract.md §"Session start".
// `report_focus` and `max_opportunities` are optional; backend must accept the
// frame and ignore unknown/missing optional fields gracefully.
export type RunParams = {
  domain: string;
  hitlMode: HitlMode;
  reportFocus?: string;
  maxOpportunities?: number;
};

export type NodeAddedEvent = {
  type: 'node_added';
  run_id: string;
  node_id: string;
  node_type: AgentNodeType;
  parent_id: string | null;
  label: string;
  opportunity_id: string | null;
  timestamp: string;
};

export type NodeStatusEvent = {
  type: 'node_status';
  run_id: string;
  node_id: string;
  status: NodeStatus;
  summary: string | null;
  timestamp: string;
};

export type EdgeActiveEvent = {
  type: 'edge_active';
  run_id: string;
  from: string;
  to: string;
  timestamp: string;
};

export type RunCompletedEvent = {
  type: 'run_completed';
  run_id: string;
  timestamp: string;
};

export type WsEvent =
  | NodeAddedEvent
  | NodeStatusEvent
  | EdgeActiveEvent
  | RunCompletedEvent;

// REST history response shape — contract.md §"REST: node history"
export type NodeHistory = {
  node_id: string;
  opportunity: Record<string, unknown> | null;
  reasoning: string | null;
  worth_it_verdict: string | null;
  worth_it_reasoning: string | null;
};

// REST report response — contract.md §"REST: run report"
export type RunReport = {
  markdown: string;
  generated_at: string;
};

// REST opportunities response — populated when the run is paused at
// human_approval. Used by the approval UI in HistoryDrawer to render
// checkboxes.
export type OpportunitySummary = {
  id: string;
  title: string;
  description: string;
};
export type RunOpportunities = {
  opportunities: OpportunitySummary[];
};

// Solution design — returned by the Architect Agent (A2A) via the
// backend proxy POST /runs/{runId}/nodes/{nodeId}/design. Field list
// mirrors architect_agent/schemas.py SolutionDesign exactly.
export type SolutionDesign = {
  proposed_stack: string[];
  components: string[];
  data_flow_summary: string;
  deployment_target: string;
  build_effort_estimate: string;
  risks: string[];
  open_questions: string[];
};
export type NodeDesignResponse = {
  design: SolutionDesign;
};
