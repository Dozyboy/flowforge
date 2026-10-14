"use client";

import { useEffect } from "react";

export const APP_NAME = "FlowForge";

/** Set the browser tab title for client-rendered pages: "Page · FlowForge". */
export function useDocumentTitle(title: string | null | undefined): void {
  useEffect(() => {
    document.title = title ? `${title} · ${APP_NAME}` : APP_NAME;
  }, [title]);
}
