import { Activity, Bot, GitBranch, KeyRound, RotateCcw, UserCheck } from "lucide-react";
import Link from "next/link";

import { Logo } from "@/components/Logo";

const FEATURES = [
  {
    icon: GitBranch,
    title: "Visual builder",
    text: "Drag triggers, AI steps, logic and integrations onto a canvas. Route on conditions or on what the AI decides.",
  },
  {
    icon: Bot,
    title: "AI that does the judgement work",
    text: "Classify, summarize, extract fields or let an agent call your APIs — with token and cost tracking.",
  },
  {
    icon: UserCheck,
    title: "Humans in the loop",
    text: "Pause for approval by email. The run continues on the approved or rejected branch.",
  },
  {
    icon: RotateCcw,
    title: "Reliable by design",
    text: "Parallel branches, retries with backoff, timeouts, and resume from the step that failed.",
  },
  {
    icon: Activity,
    title: "See every step",
    text: "Watch runs live on the canvas and inspect each step's input, output, error and duration.",
  },
  {
    icon: KeyRound,
    title: "Secrets stay secret",
    text: "Encrypted credential vault, versioned workflows, roles, API keys and an audit log.",
  },
];

export default function LandingPage() {
  return (
    <div className="min-h-full bg-white">
      <header className="mx-auto flex max-w-6xl items-center justify-between px-6 py-5">
        <Logo />
        <nav className="flex items-center gap-3 text-sm">
          <Link href="/login" className="font-medium text-slate-600 hover:text-slate-900">
            Sign in
          </Link>
          <Link
            href="/register"
            className="rounded-md bg-indigo-600 px-4 py-2 font-medium text-white hover:bg-indigo-500"
          >
            Start free
          </Link>
        </nav>
      </header>
      <main>
        <section className="mx-auto max-w-4xl px-6 pt-16 pb-20 text-center">
          <p className="mb-4 inline-block rounded-full bg-indigo-50 px-3 py-1 text-xs font-medium text-indigo-700">
            Automation with AI steps built in
          </p>
          <h1 className="text-4xl font-bold tracking-tight text-slate-900 sm:text-5xl">
            Automate the busywork, keep humans in control
          </h1>
          <p className="mx-auto mt-5 max-w-2xl text-lg text-slate-600">
            FlowForge connects webhooks, schedules, AI and your tools in visual workflows that run
            reliably — and ask a person before anything important happens.
          </p>
          <div className="mt-8 flex justify-center gap-3">
            <Link
              href="/register"
              className="rounded-md bg-indigo-600 px-5 py-3 text-sm font-semibold text-white hover:bg-indigo-500"
            >
              Build your first workflow
            </Link>
            <Link
              href="/login"
              className="rounded-md border border-slate-300 px-5 py-3 text-sm font-semibold text-slate-700 hover:bg-slate-50"
            >
              Try the demo account
            </Link>
          </div>
        </section>
        <section className="border-t border-slate-100 bg-slate-50 py-20">
          <div className="mx-auto grid max-w-6xl gap-6 px-6 sm:grid-cols-2 lg:grid-cols-3">
            {FEATURES.map(({ icon: Icon, title, text }) => (
              <div key={title} className="rounded-lg border border-slate-200 bg-white p-6">
                <Icon className="size-6 text-indigo-600" aria-hidden />
                <h2 className="mt-4 font-semibold text-slate-900">{title}</h2>
                <p className="mt-2 text-sm text-slate-600">{text}</p>
              </div>
            ))}
          </div>
        </section>
      </main>
      <footer className="py-8 text-center text-sm text-slate-500">
        FlowForge · AI workflow automation
      </footer>
    </div>
  );
}
