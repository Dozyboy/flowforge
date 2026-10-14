"use client";

import { useQuery } from "@tanstack/react-query";

import { Badge } from "@/components/ui/Badge";
import { Card, CardBody, CardHeader } from "@/components/ui/Card";
import { ErrorState, PageLoader } from "@/components/ui/Feedback";
import { useWorkspace } from "@/features/workspace/workspace-context";
import { api, errorMessage } from "@/lib/api-client";
import { queryKeys } from "@/lib/query-keys";
import type { Usage } from "@/lib/types";

function Meter({ label, used, limit }: { label: string; used: number; limit: number }) {
  const ratio = Math.min(1, used / limit);
  const color = ratio >= 0.9 ? "bg-rose-500" : ratio >= 0.7 ? "bg-amber-500" : "bg-indigo-500";
  return (
    <div>
      <div className="mb-1 flex justify-between text-sm">
        <span className="text-slate-700">{label}</span>
        <span className="text-slate-500">
          {used.toLocaleString()} / {limit.toLocaleString()}
        </span>
      </div>
      <div className="h-2 rounded-full bg-slate-100">
        <div className={`h-2 rounded-full ${color}`} style={{ width: `${ratio * 100}%` }} />
      </div>
    </div>
  );
}

export default function UsagePage() {
  const { workspace } = useWorkspace();
  const usage = useQuery({
    queryKey: queryKeys.usage(workspace.id),
    queryFn: () => api<Usage>(`/workspaces/${workspace.id}/usage`),
  });
  if (usage.isPending) return <PageLoader />;
  if (usage.isError) return <ErrorState message={errorMessage(usage.error)} />;
  const data = usage.data;
  const cost = data.llm.reduce((sum, row) => sum + Number(row.cost_usd), 0);

  return (
    <div className="space-y-6">
      <Card>
        <CardHeader
          title={
            <span className="flex items-center gap-2">
              Current plan <Badge tone="info">{data.plan.name}</Badge>
            </span>
          }
          description={`Up to ${data.plan.max_concurrent_runs} runs at the same time`}
        />
        <CardBody className="space-y-4">
          <Meter label="Workflows" used={data.workflows} limit={data.plan.max_workflows} />
          <Meter
            label="Runs this month"
            used={data.runs_this_month}
            limit={data.plan.max_runs_per_month}
          />
          <Meter label="Members" used={data.members} limit={data.plan.max_members} />
        </CardBody>
      </Card>
      <Card>
        <CardHeader
          title="AI usage this month"
          description={`Estimated cost: $${cost.toFixed(4)}`}
        />
        {data.llm.length === 0 ? (
          <CardBody>
            <p className="text-sm text-slate-500">No AI steps have run this month.</p>
          </CardBody>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full min-w-[36rem] text-sm">
              <thead className="bg-slate-50 text-left text-xs text-slate-500 uppercase">
                <tr>
                  <th className="px-5 py-2">Step type</th>
                  <th className="px-5 py-2 text-right">Calls</th>
                  <th className="px-5 py-2 text-right">Prompt tokens</th>
                  <th className="px-5 py-2 text-right">Completion tokens</th>
                  <th className="px-5 py-2 text-right">Cost (USD)</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {data.llm.map((row) => (
                  <tr key={row.kind}>
                    <td className="px-5 py-2 font-mono text-xs text-slate-700">{row.kind}</td>
                    <td className="px-5 py-2 text-right">{row.calls}</td>
                    <td className="px-5 py-2 text-right">{row.prompt_tokens.toLocaleString()}</td>
                    <td className="px-5 py-2 text-right">
                      {row.completion_tokens.toLocaleString()}
                    </td>
                    <td className="px-5 py-2 text-right font-mono">
                      {Number(row.cost_usd).toFixed(4)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </div>
  );
}
