"use client";

import { useQuery } from "@tanstack/react-query";
import { format, parseISO } from "date-fns";
import Link from "next/link";
import { useState } from "react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { PageHeader } from "@/components/PageHeader";
import { Card, CardBody, CardHeader } from "@/components/ui/Card";
import { ErrorState, PageLoader } from "@/components/ui/Feedback";
import { Select } from "@/components/ui/Field";
import { useWorkspace } from "@/features/workspace/workspace-context";
import { api, errorMessage } from "@/lib/api-client";
import { duration, percent } from "@/lib/format";
import { queryKeys } from "@/lib/query-keys";
import type { Dashboard } from "@/lib/types";

function Stat({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <Card className="px-5 py-4">
      <p className="text-sm text-slate-500">{label}</p>
      <p className="mt-1 text-2xl font-semibold text-slate-900">{value}</p>
      {hint && <p className="mt-1 text-xs text-slate-400">{hint}</p>}
    </Card>
  );
}

export default function DashboardPage() {
  const { workspace, basePath } = useWorkspace();
  const [days, setDays] = useState(14);
  const dashboard = useQuery({
    queryKey: queryKeys.dashboard(workspace.id, days),
    queryFn: () => api<Dashboard>(`/workspaces/${workspace.id}/dashboard`, { query: { days } }),
  });

  return (
    <>
      <PageHeader
        title="Dashboard"
        description="How your automations are running."
        actions={
          <Select
            aria-label="Period"
            className="w-40"
            value={days}
            onChange={(e) => setDays(Number(e.target.value))}
          >
            <option value={7}>Last 7 days</option>
            <option value={14}>Last 14 days</option>
            <option value={30}>Last 30 days</option>
          </Select>
        }
      />
      <div className="space-y-6 p-4 sm:p-8">
        {dashboard.isPending && <PageLoader />}
        {dashboard.isError && <ErrorState message={errorMessage(dashboard.error)} />}
        {dashboard.data && (
          <>
            <div className="grid gap-4 sm:grid-cols-2 xl:grid-cols-4">
              <Stat label="Runs" value={String(dashboard.data.total_runs)} />
              <Stat
                label="Success rate"
                value={percent(dashboard.data.success_rate)}
                hint={`${dashboard.data.failed} failed`}
              />
              <Stat
                label="Median duration"
                value={duration(dashboard.data.median_duration_seconds)}
              />
              <Stat
                label="AI cost"
                value={`$${Number(dashboard.data.ai_cost_usd).toFixed(4)}`}
                hint={`${dashboard.data.active_workflows} active workflows`}
              />
            </div>
            {dashboard.data.pending_approvals > 0 && (
              <Link
                href={`${basePath}/approvals`}
                className="block rounded-lg border border-amber-200 bg-amber-50 px-5 py-3 text-sm text-amber-900 hover:bg-amber-100"
              >
                {dashboard.data.pending_approvals} run(s) are waiting for approval →
              </Link>
            )}
            <div className="grid gap-6 xl:grid-cols-3">
              <Card className="xl:col-span-2">
                <CardHeader title="Runs per day" />
                <CardBody>
                  <div className="h-72">
                    <ResponsiveContainer width="100%" height="100%">
                      <BarChart
                        data={dashboard.data.daily.map((d) => ({
                          ...d,
                          label: format(parseISO(d.day), "MMM d"),
                        }))}
                        margin={{ top: 8, right: 8, bottom: 0, left: -16 }}
                      >
                        <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#e2e8f0" />
                        <XAxis dataKey="label" tick={{ fontSize: 12, fill: "#64748b" }} />
                        <YAxis allowDecimals={false} tick={{ fontSize: 12, fill: "#64748b" }} />
                        <Tooltip cursor={{ fill: "#f1f5f9" }} />
                        <Legend wrapperStyle={{ fontSize: 12 }} />
                        <Bar dataKey="succeeded" name="Succeeded" stackId="a" fill="#10b981" />
                        <Bar dataKey="failed" name="Failed" stackId="a" fill="#f43f5e" />
                        <Bar
                          dataKey="other"
                          name="Waiting / other"
                          stackId="a"
                          fill="#94a3b8"
                          radius={[3, 3, 0, 0]}
                        />
                      </BarChart>
                    </ResponsiveContainer>
                  </div>
                </CardBody>
              </Card>
              <Card>
                <CardHeader title="Failing workflows" />
                <CardBody>
                  {dashboard.data.failing_workflows.length === 0 ? (
                    <p className="text-sm text-slate-500">No failures in this period.</p>
                  ) : (
                    <ul className="space-y-3">
                      {dashboard.data.failing_workflows.map((wf) => (
                        <li key={wf.workflow_id} className="flex justify-between text-sm">
                          <Link
                            href={`${basePath}/runs?workflow=${wf.workflow_id}&status=failed`}
                            className="truncate text-indigo-700 hover:underline"
                          >
                            {wf.name}
                          </Link>
                          <span className="text-rose-600">{wf.failures}</span>
                        </li>
                      ))}
                    </ul>
                  )}
                </CardBody>
              </Card>
            </div>
          </>
        )}
      </div>
    </>
  );
}
