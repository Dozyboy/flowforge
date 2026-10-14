import Link from "next/link";

import { Logo } from "@/components/Logo";

export const metadata = { title: "Page not found" };

export default function NotFound() {
  return (
    <div className="flex min-h-full flex-col items-center justify-center gap-6 px-4 py-16 text-center">
      <Logo />
      <div>
        <p className="text-sm font-semibold text-indigo-600">404</p>
        <h1 className="mt-1 text-2xl font-semibold text-slate-900">Page not found</h1>
        <p className="mt-2 text-sm text-slate-600">
          The page you are looking for does not exist or was moved.
        </p>
      </div>
      <Link
        href="/app"
        className="rounded-md bg-indigo-600 px-4 py-2 text-sm font-medium text-white hover:bg-indigo-500"
      >
        Go to the app
      </Link>
    </div>
  );
}
