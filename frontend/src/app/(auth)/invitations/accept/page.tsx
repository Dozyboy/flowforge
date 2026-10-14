"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useState } from "react";

import { Button, buttonClasses } from "@/components/ui/Button";
import { ErrorState, Spinner } from "@/components/ui/Feedback";
import { api, errorMessage } from "@/lib/api-client";
import { useAuth } from "@/lib/auth";
import type { WorkspaceSummary } from "@/lib/types";

function AcceptInvitation() {
  const token = useSearchParams().get("token") ?? "";
  const router = useRouter();
  const { status, me, reload } = useAuth();
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const returnTo = `/invitations/accept?token=${encodeURIComponent(token)}`;

  if (status === "loading") return <Spinner />;

  if (status === "anonymous") {
    return (
      <div className="space-y-4">
        <h1 className="text-lg font-semibold text-slate-900">You have been invited</h1>
        <p className="text-sm text-slate-600">
          Sign in or create an account with the email address the invitation was sent to.
        </p>
        <div className="flex gap-2">
          <Link
            href={`/login?next=${encodeURIComponent(returnTo)}`}
            className={`${buttonClasses()} flex-1`}
          >
            Sign in
          </Link>
          <Link
            href={`/register?next=${encodeURIComponent(returnTo)}`}
            className={`${buttonClasses("secondary")} flex-1`}
          >
            Create account
          </Link>
        </div>
      </div>
    );
  }

  const accept = async () => {
    setLoading(true);
    setError(null);
    try {
      const workspace = await api<WorkspaceSummary>("/invitations/accept", {
        method: "POST",
        body: { token },
      });
      await reload();
      router.replace(`/app/${workspace.id}`);
    } catch (err) {
      setError(errorMessage(err));
      setLoading(false);
    }
  };

  return (
    <div className="space-y-4">
      <h1 className="text-lg font-semibold text-slate-900">Join the workspace</h1>
      <p className="text-sm text-slate-600">
        You are signed in as <strong>{me?.user.email}</strong>.
      </p>
      {error && <ErrorState message={error} />}
      <Button className="w-full" onClick={accept} loading={loading} disabled={!token}>
        Accept invitation
      </Button>
    </div>
  );
}

export default function AcceptInvitationPage() {
  return (
    <Suspense>
      <AcceptInvitation />
    </Suspense>
  );
}
