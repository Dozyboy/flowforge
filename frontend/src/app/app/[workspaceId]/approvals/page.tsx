"use client";

import { useQuery } from "@tanstack/react-query";
import { UserCheck } from "lucide-react";
import Link from "next/link";

import { PageHeader } from "@/components/PageHeader";
import { Card } from "@/components/ui/Card";
import { EmptyState, ErrorState, PageLoader } from "@/components/ui/Feedback";
import { useWorkspace } from "@/features/workspace/workspace-context";
import { api, errorMessage } from "@/lib/api-client";
import { formatDateTime, timeAgo } from "@/lib/format";
import { queryKeys } from "@/lib/query-keys";
import type { PendingApproval } from "@/lib/types";

export default function ApprovalsPage() {
  const { workspace, basePath } = useWorkspace();
  const approvals = useQuery({
    queryKey: queryKeys.approvals(workspace.id),
    queryFn: () => api<PendingApproval[]>(`/workspaces/${workspace.id}/approvals`),
  });

  return (
    <>
      <PageHeader
        title="Approvals"
        description="Runs paused until someone approves. Approvers decide from the link in their email."
      />
      <div className="space-y-4 p-4 sm:p-8">
        {approvals.isPending && <PageLoader />}
        {approvals.isError && <ErrorState message={errorMessage(approvals.error)} />}
        {approvals.data?.length === 0 && (
          <Card>
            <EmptyState icon={<UserCheck className="size-5" />} title="Nothing is waiting" />
          </Card>
        )}
        {approvals.data?.map((approval) => (
          <Card key={approval.id} className="p-5">
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div>
                <p className="font-semibold text-slate-900">{approval.workflow_name}</p>
                <p className="text-xs text-slate-500">
                  Step <code>{approval.node_id}</code> · requested {timeAgo(approval.created_at)} ·
                  expires {formatDateTime(approval.expires_at)}
                </p>
              </div>
              <Link
                href={`${basePath}/runs/${approval.run_id}`}
                className="text-sm font-medium text-indigo-600 hover:underline"
              >
                View run
              </Link>
            </div>
            <p className="mt-3 rounded-md bg-slate-50 px-3 py-2 text-sm whitespace-pre-wrap text-slate-700">
              {approval.message}
            </p>
            <p className="mt-2 text-xs text-slate-500">Sent to {approval.approvers.join(", ")}</p>
          </Card>
        ))}
      </div>
    </>
  );
}
