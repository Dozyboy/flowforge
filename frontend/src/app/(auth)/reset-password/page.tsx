"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { Suspense, useState, type FormEvent } from "react";

import { Button } from "@/components/ui/Button";
import { ErrorState } from "@/components/ui/Feedback";
import { Field, Input } from "@/components/ui/Field";
import { api, errorMessage } from "@/lib/api-client";

function ResetPasswordForm() {
  const token = useSearchParams().get("token") ?? "";
  const [password, setPassword] = useState("");
  const [done, setDone] = useState(false);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const onSubmit = async (event: FormEvent) => {
    event.preventDefault();
    if (password.length < 8) {
      setError("Use at least 8 characters");
      return;
    }
    setLoading(true);
    setError(null);
    try {
      await api("/auth/reset-password", {
        method: "POST",
        body: { token, password },
        auth: false,
      });
      setDone(true);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setLoading(false);
    }
  };

  if (done) {
    return (
      <div className="space-y-3">
        <h1 className="text-lg font-semibold text-slate-900">Password updated</h1>
        <p className="text-sm text-slate-600">You have been signed out on all devices.</p>
        <Link href="/login" className="text-sm text-indigo-600 hover:underline">
          Sign in with your new password
        </Link>
      </div>
    );
  }

  return (
    <form onSubmit={onSubmit} className="space-y-4">
      <h1 className="text-lg font-semibold text-slate-900">Choose a new password</h1>
      {!token && <ErrorState message="This link is missing its token." />}
      {error && <ErrorState message={error} />}
      <Field label="New password" htmlFor="password" hint="At least 8 characters">
        <Input
          id="password"
          type="password"
          autoComplete="new-password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
        />
      </Field>
      <Button type="submit" className="w-full" loading={loading} disabled={!token}>
        Update password
      </Button>
    </form>
  );
}

export default function ResetPasswordPage() {
  return (
    <Suspense>
      <ResetPasswordForm />
    </Suspense>
  );
}
