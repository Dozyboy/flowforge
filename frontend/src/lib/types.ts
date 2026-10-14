// Mirrors the backend Pydantic schemas (backend/app/schemas). Keep in sync when the API changes.

export type Role = "viewer" | "member" | "admin" | "owner";

export interface User {
  id: string;
  email: string;
  full_name: string;
  is_email_verified: boolean;
  created_at: string;
}

export interface WorkspaceSummary {
  id: string;
  name: string;
  slug: string;
  plan: string;
  role: Role;
}

export interface Me {
  user: User;
  workspaces: WorkspaceSummary[];
}

export interface TokenResponse {
  access_token: string;
  token_type: string;
  expires_in: number;
  user: User;
}

export interface Page<T> {
  items: T[];
  total: number;
  limit: number;
  offset: number;
}

// --- workflow graph (React Flow compatible JSON stored by the backend) ------------------------

export interface StepSettings {
  retries?: number;
  retry_delay_seconds?: number;
  timeout_seconds?: number;
  continue_on_error?: boolean;
}

export interface GraphNode {
  id: string;
  type: string;
  position: { x: number; y: number };
  data: { label: string; config: Record<string, unknown>; settings?: StepSettings };
}

export interface GraphEdge {
  id: string;
  source: string;
  target: string;
  sourceHandle?: string | null;
}

export interface WorkflowGraph {
  nodes: GraphNode[];
  edges: GraphEdge[];
}

export interface GraphIssue {
  node_id: string | null;
  message: string;
}

export type RunStatus = "queued" | "running" | "waiting" | "succeeded" | "failed" | "cancelled";
export type StepStatus = "running" | "succeeded" | "failed" | "skipped" | "waiting";

export interface WorkflowSummary {
  id: string;
  name: string;
  description: string;
  is_active: boolean;
  trigger_type: string | null;
  published_version: number | null;
  last_run_status: RunStatus | null;
  last_run_at: string | null;
  runs_last_7_days: number;
  updated_at: string;
}

export interface Workflow {
  id: string;
  name: string;
  description: string;
  draft_graph: WorkflowGraph;
  is_active: boolean;
  published_version_id: string | null;
  has_webhook_secret: boolean;
  schedule_cron: string | null;
  schedule_timezone: string | null;
  next_run_at: string | null;
  created_at: string;
  updated_at: string;
}

export interface WorkflowDetail extends Workflow {
  issues: GraphIssue[];
  published_version: number | null;
  webhook_url: string;
}

export interface SaveResult {
  workflow: Workflow;
  issues: GraphIssue[];
}

export interface PublishResult {
  version: number;
  webhook_secret: string | null;
}

export interface Version {
  id: string;
  version: number;
  note: string;
  created_by_id: string | null;
  created_at: string;
}

export interface GraphDiff {
  added_nodes: string[];
  removed_nodes: string[];
  changed_nodes: { node_id: string; config_fields: string[] }[];
  added_edges: string[];
  removed_edges: string[];
}

export interface Template {
  id: string;
  name: string;
  description: string;
  category: string;
  graph: WorkflowGraph;
}

export type NodeCategory = "trigger" | "ai" | "logic" | "data" | "integration";

export interface JsonSchema {
  type?: string | string[];
  title?: string;
  description?: string;
  enum?: unknown[];
  default?: unknown;
  minimum?: number;
  maximum?: number;
  minLength?: number;
  items?: JsonSchema;
  properties?: Record<string, JsonSchema>;
  required?: string[];
  "x-ui"?: "textarea" | "json" | "tags" | "credential" | "workflow";
  "x-credential-types"?: string[];
}

export interface NodeTypeInfo {
  type: string;
  label: string;
  category: NodeCategory;
  description: string;
  icon: string;
  config_schema: JsonSchema;
  static_handles: string[];
  dynamic_handles_key: string | null;
  dynamic_handles_extra: string[];
}

// --- runs ---------------------------------------------------------------------------------------

export type TriggerType = "manual" | "webhook" | "schedule" | "sub_workflow" | "retry";

export interface RunSummary {
  id: string;
  workflow_id: string;
  workflow_name: string;
  status: RunStatus;
  trigger_type: TriggerType;
  error: string | null;
  retry_of_id: string | null;
  created_at: string;
  started_at: string | null;
  finished_at: string | null;
}

export interface Step {
  id: string;
  node_id: string;
  node_type: string;
  status: StepStatus;
  attempt: number;
  input: unknown;
  output: unknown;
  branch: string | null;
  error: string | null;
  started_at: string | null;
  finished_at: string | null;
  duration_ms: number | null;
  resume_at: string | null;
}

export interface ChildRun {
  id: string;
  workflow_id: string;
  status: RunStatus;
  error: string | null;
  trigger_payload: Record<string, unknown>;
}

export interface RunDetail extends RunSummary {
  version_id: string | null;
  graph: WorkflowGraph;
  trigger_payload: Record<string, unknown>;
  cancel_requested: boolean;
  steps: Step[];
  children: ChildRun[];
}

export interface PendingApproval {
  id: string;
  run_id: string;
  workflow_name: string;
  node_id: string;
  message: string;
  approvers: string[];
  expires_at: string;
  created_at: string;
}

export interface PublicApproval {
  workflow_name: string;
  message: string;
  status: "pending" | "approved" | "rejected" | "expired";
  expires_at: string;
  decided_at: string | null;
  decided_by: string | null;
  run_status: RunStatus;
}

// --- credentials, workspace ---------------------------------------------------------------------

export interface CredentialField {
  name: string;
  label: string;
  secret: boolean;
  multiline: boolean;
}

export interface CredentialType {
  type: string;
  label: string;
  description: string;
  fields: CredentialField[];
}

export interface Credential {
  id: string;
  name: string;
  type: string;
  created_at: string;
  updated_at: string;
}

export interface Member {
  id: string;
  role: Role;
  user: User;
  created_at: string;
}

export interface Invitation {
  id: string;
  email: string;
  role: Role;
  expires_at: string;
  created_at: string;
}

export interface ApiKey {
  id: string;
  name: string;
  prefix: string;
  last_used_at: string | null;
  created_at: string;
}

export interface ApiKeyCreated extends ApiKey {
  key: string;
}

export interface Usage {
  plan: {
    code: string;
    name: string;
    max_workflows: number;
    max_runs_per_month: number;
    max_concurrent_runs: number;
    max_members: number;
  };
  workflows: number;
  runs_this_month: number;
  members: number;
  llm: {
    kind: string;
    calls: number;
    prompt_tokens: number;
    completion_tokens: number;
    cost_usd: string;
  }[];
}

export interface Dashboard {
  period_days: number;
  total_runs: number;
  succeeded: number;
  failed: number;
  success_rate: number | null;
  median_duration_seconds: number | null;
  active_workflows: number;
  pending_approvals: number;
  ai_cost_usd: string;
  daily: { day: string; succeeded: number; failed: number; other: number }[];
  failing_workflows: { workflow_id: string; name: string; failures: number }[];
}

export interface AuditLogEntry {
  id: string;
  action: string;
  actor_user_id: string | null;
  actor_api_key_id: string | null;
  target_type: string | null;
  target_id: string | null;
  details: Record<string, unknown>;
  ip_address: string | null;
  created_at: string;
}

export interface RealtimeEvent {
  type: string;
  data: Record<string, unknown>;
}
