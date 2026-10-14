"use client";

import type { ReactNode } from "react";

import { useDocumentTitle } from "@/lib/use-document-title";

export function PageHeader({
  title,
  description,
  actions,
  documentTitle,
}: {
  title: string;
  description?: ReactNode;
  actions?: ReactNode;
  /** Tab title when `title` is not plain text. */
  documentTitle?: string;
}) {
  useDocumentTitle(documentTitle ?? (typeof title === "string" ? title : null));
  return (
    <div className="flex flex-wrap items-end justify-between gap-4 border-b border-slate-200 bg-white px-4 py-5 sm:px-8 sm:py-6">
      <div>
        <h1 className="text-xl font-semibold text-slate-900">{title}</h1>
        {description && <p className="mt-1 text-sm text-slate-500">{description}</p>}
      </div>
      {actions && <div className="flex items-center gap-2">{actions}</div>}
    </div>
  );
}
