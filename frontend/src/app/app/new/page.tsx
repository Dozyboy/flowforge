"use client";

import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";

import { Logo } from "@/components/Logo";
import { Button } from "@/components/ui/Button";
import { ErrorState } from "@/components/ui/Feedback";
import { Field, Input } from "@/components/ui/Field";
import { api, errorMessage } from "@/lib/api-client";
import { useAuth } from "@/lib/auth";
import type { WorkspaceSummary as Workspace } from "@/lib/types";

export default function NewWorkspacePage() {
  const { me, reload } = useAuth();
  const router = useRouter();
  const [name, setName] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const onSubmit = async (event: FormEvent) => {
    event.preventDefault();
    setLoading(true);
    setError(null);
    try {
      const workspace = await api<Workspace>("/workspaces", { method: "POST", body: { name } });
      await reload();
      router.replace(`/app/${workspace.id}/workflows?onboarding=1`);
    } catch (err) {
      setError(errorMessage(err));
      setLoading(false);
    }
  };

  return (
    <div className="flex min-h-full flex-col items-center justify-center px-4">
      <div className="mb-8">
        <Logo href="/app" />
      </div>
      <form
        onSubmit={onSubmit}
        className="w-full max-w-md space-y-5 rounded-lg border border-slate-200 bg-white p-6 shadow-sm"
      >
        <div>
          <h1 className="text-lg font-semibold text-slate-900">
            {me?.workspaces.length ? "Create another workspace" : "Set up your workspace"}
          </h1>
          <p className="mt-1 text-sm text-slate-500">
            A workspace holds your team&apos;s workflows, credentials and run history.
          </p>
        </div>
        {error && <ErrorState message={error} />}
        <Field label="Company name" htmlFor="name">
          <Input
            id="name"
            required
            maxLength={120}
            placeholder="Northwind Coffee"
            value={name}
            onChange={(e) => setName(e.target.value)}
          />
        </Field>
        <Button type="submit" className="w-full" loading={loading} disabled={!name.trim()}>
          Create workspace
        </Button>
      </form>
    </div>
  );
}
