"use client";

import { useQuery } from "@tanstack/react-query";

import { Card } from "@/components/ui/Card";
import { ErrorState, PageLoader } from "@/components/ui/Feedback";
import { useWorkspace } from "@/features/workspace/workspace-context";
import { api, errorMessage } from "@/lib/api-client";
import { formatDateTime } from "@/lib/format";
import { queryKeys } from "@/lib/query-keys";
import type { AuditLogEntry, Member } from "@/lib/types";

export default function AuditLogPage() {
  const { workspace } = useWorkspace();
  const logs = useQuery({
    queryKey: queryKeys.auditLogs(workspace.id),
    queryFn: () =>
      api<AuditLogEntry[]>(`/workspaces/${workspace.id}/audit-logs`, { query: { limit: 100 } }),
  });
  const members = useQuery({
    queryKey: queryKeys.members(workspace.id),
    queryFn: () => api<Member[]>(`/workspaces/${workspace.id}/members`),
  });
  const names = new Map(members.data?.map((m) => [m.user.id, m.user.full_name]));

  if (logs.isPending) return <PageLoader />;
  if (logs.isError) return <ErrorState message={errorMessage(logs.error)} />;

  const actor = (entry: AuditLogEntry) => {
    if (entry.actor_api_key_id) return "API key";
    if (entry.actor_user_id) return names.get(entry.actor_user_id) ?? "Former member";
    return "System";
  };

  return (
    <Card className="overflow-hidden">
      <div className="overflow-x-auto">
        <table className="w-full min-w-[36rem] text-sm">
          <thead className="bg-slate-50 text-left text-xs text-slate-500 uppercase">
            <tr>
              <th className="px-5 py-2">When</th>
              <th className="px-5 py-2">Who</th>
              <th className="px-5 py-2">Action</th>
              <th className="px-5 py-2">Details</th>
              <th className="px-5 py-2">IP</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {logs.data.map((entry) => (
              <tr key={entry.id} className="align-top">
                <td className="px-5 py-2 whitespace-nowrap text-slate-500">
                  {formatDateTime(entry.created_at)}
                </td>
                <td className="px-5 py-2 text-slate-700">{actor(entry)}</td>
                <td className="px-5 py-2 font-mono text-xs text-slate-800">{entry.action}</td>
                <td className="max-w-sm truncate px-5 py-2 font-mono text-xs text-slate-500">
                  {Object.keys(entry.details).length ? JSON.stringify(entry.details) : "—"}
                </td>
                <td className="px-5 py-2 text-slate-500">{entry.ip_address ?? "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </Card>
  );
}
