import Link from "next/link";

export function Logo({ href = "/" }: { href?: string }) {
  return (
    <Link href={href} className="flex items-center gap-2 font-semibold text-slate-900">
      <span className="flex size-7 items-center justify-center rounded-md bg-indigo-600 text-sm text-white">
        FF
      </span>
      FlowForge
    </Link>
  );
}
