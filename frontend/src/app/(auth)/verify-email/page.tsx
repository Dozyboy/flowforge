"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense, useEffect, useRef, useState } from "react";

import { Spinner } from "@/components/ui/Feedback";
import { api, errorMessage } from "@/lib/api-client";
import { useAuth } from "@/lib/auth";

type Result = { ok: true } | { ok: false; error: string };

function VerifyEmail() {
  const token = useSearchParams().get("token");
  const { status: authStatus, reload } = useAuth();
  const [result, setResult] = useState<Result | null>(null);
  const started = useRef(false);

  useEffect(() => {
    if (!token || started.current) return;
    started.current = true;
    api("/auth/verify-email", { method: "POST", body: { token }, auth: false })
      .then(() => {
        setResult({ ok: true });
        if (authStatus === "authenticated") void reload();
      })
      .catch((err: unknown) => setResult({ ok: false, error: errorMessage(err) }));
  }, [token, authStatus, reload]);

  const outcome: Result | null = token
    ? result
    : { ok: false, error: "This link is missing its token." };

  if (!outcome) {
    return (
      <div className="flex items-center gap-3 text-sm text-slate-600">
        <Spinner /> Verifying your email…
      </div>
    );
  }
  return (
    <div className="space-y-3">
      <h1 className="text-lg font-semibold text-slate-900">
        {outcome.ok ? "Email verified" : "Verification failed"}
      </h1>
      <p className="text-sm text-slate-600">
        {outcome.ok ? "Thanks! Your email address is confirmed." : outcome.error}
      </p>
      <Link href="/app" className="text-sm text-indigo-600 hover:underline">
        Continue to FlowForge
      </Link>
    </div>
  );
}

export default function VerifyEmailPage() {
  return (
    <Suspense>
      <VerifyEmail />
    </Suspense>
  );
}
