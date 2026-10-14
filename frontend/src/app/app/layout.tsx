"use client";

import { usePathname, useRouter } from "next/navigation";
import { useEffect } from "react";

import { PageLoader } from "@/components/ui/Feedback";
import { useAuth } from "@/lib/auth";

export default function AuthenticatedLayout({ children }: { children: React.ReactNode }) {
  const { status } = useAuth();
  const router = useRouter();
  const pathname = usePathname();

  useEffect(() => {
    if (status === "anonymous") router.replace(`/login?next=${encodeURIComponent(pathname)}`);
  }, [status, router, pathname]);

  if (status !== "authenticated") return <PageLoader />;
  return <>{children}</>;
}
