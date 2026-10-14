import {
  Bot,
  Box,
  Braces,
  Clock,
  GitFork,
  Globe,
  Hourglass,
  Mail,
  Merge,
  MessageSquare,
  Play,
  Repeat,
  ScrollText,
  Send,
  Sheet,
  Sparkles,
  Split,
  UserCheck,
  Webhook,
  Workflow,
  type LucideIcon,
} from "lucide-react";

const ICONS: Record<string, LucideIcon> = {
  play: Play,
  webhook: Webhook,
  clock: Clock,
  sparkles: Sparkles,
  bot: Bot,
  split: Split,
  "git-fork": GitFork,
  merge: Merge,
  hourglass: Hourglass,
  "user-check": UserCheck,
  workflow: Workflow,
  repeat: Repeat,
  braces: Braces,
  "scroll-text": ScrollText,
  globe: Globe,
  mail: Mail,
  slack: MessageSquare,
  send: Send,
  sheet: Sheet,
};

export function NodeIcon({ name, className }: { name: string; className?: string }) {
  const Icon = ICONS[name] ?? Box;
  return <Icon className={className} aria-hidden />;
}

export const CATEGORY_STYLE: Record<string, { label: string; color: string }> = {
  trigger: { label: "Triggers", color: "bg-emerald-100 text-emerald-700" },
  ai: { label: "AI", color: "bg-violet-100 text-violet-700" },
  logic: { label: "Logic", color: "bg-amber-100 text-amber-700" },
  data: { label: "Data", color: "bg-sky-100 text-sky-700" },
  integration: { label: "Integrations", color: "bg-rose-100 text-rose-700" },
};
