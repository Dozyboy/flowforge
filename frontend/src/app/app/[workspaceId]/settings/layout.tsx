"use client";

import { PageHeader } from "@/components/PageHeader";
import { TabLinks } from "@/components/ui/Tabs";
import { useWorkspace } from "@/features/workspace/workspace-context";

export default function SettingsLayout({ children }: { children: React.ReactNode }) {
  const { basePath, can } = useWorkspace();
  const base = `${basePath}/settings`;
  const tabs = [
    { href: base, label: "General" },
    { href: `${base}/members`, label: "Members" },
    ...(can("admin")
      ? [
          { href: `${base}/api-keys`, label: "API keys" },
          { href: `${base}/audit-log`, label: "Audit log" },
        ]
      : []),
    { href: `${base}/usage`, label: "Plan & usage" },
  ];
  return (
    <>
      <PageHeader title="Settings" />
      <div className="space-y-6 p-4 sm:p-8">
        <TabLinks tabs={tabs} />
        {children}
      </div>
    </>
  );
}
