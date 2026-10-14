"use client";

import { useRouter } from "next/navigation";
import { useEffect } from "react";

import { PageLoader } from "@/components/ui/Feedback";
import { useAuth } from "@/lib/auth";

export default function AppIndexPage() {
  const { me } = useAuth();
  const router = useRouter();

  useEffect(() => {
    if (!me) return;
    const first = me.workspaces[0];
    router.replace(first ? `/app/${first.id}` : "/app/new");
  }, [me, router]);

  return <PageLoader />;
}
