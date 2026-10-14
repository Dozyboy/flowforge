"use client";

import { useMutation, useQuery } from "@tanstack/react-query";
import { useParams } from "next/navigation";
import { useState } from "react";

import { Logo } from "@/components/Logo";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { ErrorState, Spinner } from "@/components/ui/Feedback";
import { Field, Input, Textarea } from "@/components/ui/Field";
import { api, errorMessage } from "@/lib/api-client";
import { formatDateTime } from "@/lib/format";
import type { PublicApproval } from "@/lib/types";

const STATUS_TONE = {
  pending: "warning",
  approved: "success",
  rejected: "danger",
  expired: "neutral",
} as const;

/** Public page opened from the approval email. The token in the URL is the only credential. */
export default function ApprovalPage() {
  const { token } = useParams<{ token: string }>();
  const [name, setName] = useState("");
  const [comment, setComment] = useState("");
  const approval = useQuery({
    queryKey: ["public-approval", token],
    queryFn: () => api<PublicApproval>(`/approvals/${token}`, { auth: false }),
    retry: false,
  });
  const decide = useMutation({
    mutationFn: (decision: "approve" | "reject") =>
      api<PublicApproval>(`/approvals/${token}`, {
        method: "POST",
        body: { decision, name: name || null, comment: comment || null },
        auth: false,
      }),
    onSuccess: () => void approval.refetch(),
  });

  return (
    <div className="flex min-h-full flex-col items-center px-4 py-12">
      <Logo />
      <div className="mt-8 w-full max-w-lg rounded-lg border border-slate-200 bg-white p-6 shadow-sm">
        {approval.isPending && <Spinner />}
        {approval.isError && <ErrorState message={errorMessage(approval.error)} />}
        {approval.data && (
          <div className="space-y-5">
            <div className="flex items-start justify-between gap-3">
              <div>
                <p className="text-xs font-medium tracking-wide text-slate-500 uppercase">
                  Approval requested
                </p>
                <h1 className="text-lg font-semibold text-slate-900">
                  {approval.data.workflow_name}
                </h1>
              </div>
              <Badge tone={STATUS_TONE[approval.data.status]}>{approval.data.status}</Badge>
            </div>
            <p className="rounded-md bg-slate-50 px-4 py-3 text-sm whitespace-pre-wrap text-slate-800">
              {approval.data.message}
            </p>
            {approval.data.status === "pending" ? (
              <>
                <Field label="Your name (optional)" htmlFor="approver-name">
                  <Input
                    id="approver-name"
                    value={name}
                    onChange={(e) => setName(e.target.value)}
                  />
                </Field>
                <Field label="Comment (optional)" htmlFor="approver-comment">
                  <Textarea
                    id="approver-comment"
                    rows={3}
                    value={comment}
                    onChange={(e) => setComment(e.target.value)}
                  />
                </Field>
                {decide.isError && <ErrorState message={errorMessage(decide.error)} />}
                <div className="flex gap-2">
                  <Button
                    className="flex-1"
                    onClick={() => decide.mutate("approve")}
                    loading={decide.isPending && decide.variables === "approve"}
                  >
                    Approve
                  </Button>
                  <Button
                    className="flex-1"
                    variant="danger"
                    onClick={() => decide.mutate("reject")}
                    loading={decide.isPending && decide.variables === "reject"}
                  >
                    Reject
                  </Button>
                </div>
                <p className="text-xs text-slate-500">
                  This link expires {formatDateTime(approval.data.expires_at)}.
                </p>
              </>
            ) : (
              <p className="text-sm text-slate-600">
                {approval.data.status === "expired"
                  ? "This request expired before anyone decided."
                  : `Decided ${formatDateTime(approval.data.decided_at)}${
                      approval.data.decided_by ? ` by ${approval.data.decided_by}` : ""
                    }. The workflow has continued.`}
              </p>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
