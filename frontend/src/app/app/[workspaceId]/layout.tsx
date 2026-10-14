"use client";

import { useQueryClient } from "@tanstack/react-query";
import { Menu } from "lucide-react";
import Link from "next/link";
import { useParams, usePathname } from "next/navigation";
import { useCallback, useEffect, useState } from "react";

import { AppSidebar } from "@/components/AppSidebar";
import { EmailVerificationBanner } from "@/components/EmailVerificationBanner";
import { Logo } from "@/components/Logo";
import { WorkspaceProvider } from "@/features/workspace/workspace-context";
import { useAuth } from "@/lib/auth";
import { queryKeys } from "@/lib/query-keys";
import { useWorkspaceEvents } from "@/lib/realtime";
import { liveRunEvents } from "@/lib/run-events";
import type { RealtimeEvent } from "@/lib/types";

function WorkspaceShell({
  workspaceId,
  children,
}: {
  workspaceId: string;
  children: React.ReactNode;
}) {
  const queryClient = useQueryClient();

  const onEvent = useCallback(
    (event: RealtimeEvent) => {
      liveRunEvents.emit(event);
      if (event.type === "run.updated") {
        void queryClient.invalidateQueries({ queryKey: queryKeys.runs(workspaceId) });
        void queryClient.invalidateQueries({ queryKey: queryKeys.approvals(workspaceId) });
        void queryClient.invalidateQueries({ queryKey: queryKeys.workflows(workspaceId) });
      }
      if (event.type === "step.updated") {
        const runId = String(event.data.run_id);
        void queryClient.invalidateQueries({ queryKey: queryKeys.run(workspaceId, runId) });
      }
    },
    [queryClient, workspaceId],
  );
  const onReconnect = useCallback(() => void queryClient.invalidateQueries(), [queryClient]);
  const connection = useWorkspaceEvents(workspaceId, onEvent, onReconnect);

  const pathname = usePathname();
  // The mobile menu remembers the page it was opened on, so navigating closes it.
  const [menuOpenedAt, setMenuOpenedAt] = useState<string | null>(null);
  const menuOpen = menuOpenedAt === pathname;
  const setMenuOpen = (open: boolean) => setMenuOpenedAt(open ? pathname : null);
  useEffect(() => {
    if (!menuOpen) return;
    const onKey = (event: KeyboardEvent) => event.key === "Escape" && setMenuOpenedAt(null);
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [menuOpen]);

  return (
    <div className="flex h-full">
      <AppSidebar connection={connection} open={menuOpen} onClose={() => setMenuOpen(false)} />
      {menuOpen && (
        <div
          className="fixed inset-0 z-30 bg-slate-900/40 lg:hidden"
          aria-hidden
          onClick={() => setMenuOpen(false)}
        />
      )}
      <main className="flex min-w-0 flex-1 flex-col overflow-y-auto">
        <div className="sticky top-0 z-20 flex items-center gap-3 border-b border-slate-200 bg-white px-4 py-2.5 lg:hidden">
          <button
            type="button"
            onClick={() => setMenuOpen(true)}
            aria-label="Open menu"
            aria-controls="app-sidebar"
            aria-expanded={menuOpen}
            className="rounded p-1.5 text-slate-600 hover:bg-slate-100"
          >
            <Menu className="size-5" />
          </button>
          <Logo href="/app" />
        </div>
        <EmailVerificationBanner />
        {children}
      </main>
    </div>
  );
}

export default function WorkspaceLayout({ children }: { children: React.ReactNode }) {
  const { workspaceId } = useParams<{ workspaceId: string }>();
  const { me } = useAuth();
  const workspace = me?.workspaces.find((ws) => ws.id === workspaceId);

  if (!workspace) {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-3 text-sm text-slate-600">
        <p>This workspace does not exist or you do not have access to it.</p>
        <Link href="/app" className="text-indigo-600 hover:underline">
          Go to your workspaces
        </Link>
      </div>
    );
  }

  return (
    <WorkspaceProvider workspace={workspace}>
      <WorkspaceShell workspaceId={workspace.id}>{children}</WorkspaceShell>
    </WorkspaceProvider>
  );
}
