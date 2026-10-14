// Central place for TanStack Query keys, so realtime events can invalidate the right caches.
export const queryKeys = {
  workflows: (ws: string) => ["workflows", ws] as const,
  workflow: (ws: string, id: string) => ["workflows", ws, id] as const,
  versions: (ws: string, id: string) => ["workflows", ws, id, "versions"] as const,
  runs: (ws: string) => ["runs", ws] as const,
  runList: (ws: string, filters: Record<string, string | number | undefined>) =>
    ["runs", ws, "list", filters] as const,
  run: (ws: string, id: string) => ["runs", ws, "detail", id] as const,
  dashboard: (ws: string, days: number) => ["dashboard", ws, days] as const,
  approvals: (ws: string) => ["approvals", ws] as const,
  credentials: (ws: string) => ["credentials", ws] as const,
  members: (ws: string) => ["members", ws] as const,
  invitations: (ws: string) => ["invitations", ws] as const,
  apiKeys: (ws: string) => ["api-keys", ws] as const,
  usage: (ws: string) => ["usage", ws] as const,
  auditLogs: (ws: string) => ["audit-logs", ws] as const,
  nodeTypes: ["node-types"] as const,
  credentialTypes: ["credential-types"] as const,
  templates: ["templates"] as const,
};
