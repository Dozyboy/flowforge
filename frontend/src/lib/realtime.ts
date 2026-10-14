"use client";

import { useEffect, useRef, useState } from "react";

import { api } from "@/lib/api-client";
import type { RealtimeEvent } from "@/lib/types";

const MAX_BACKOFF_MS = 15_000;

export type ConnectionState = "connecting" | "open" | "closed";

export function websocketUrl(ticket: string): string {
  const base = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
  return `${base.replace(/^http/, "ws")}/api/v1/ws?ticket=${encodeURIComponent(ticket)}`;
}

/**
 * Subscribes to live events for a workspace. Reconnects with exponential backoff and calls
 * `onReconnect` so callers can refetch anything missed while disconnected (pub/sub does not
 * replay events; see docs/adr/0006-realtime-websocket-and-sse.md).
 */
export function useWorkspaceEvents(
  workspaceId: string,
  onEvent: (event: RealtimeEvent) => void,
  onReconnect: () => void,
): ConnectionState {
  const [state, setState] = useState<ConnectionState>("connecting");
  const handlers = useRef({ onEvent, onReconnect });

  useEffect(() => {
    handlers.current = { onEvent, onReconnect };
  });

  useEffect(() => {
    let socket: WebSocket | null = null;
    let stopped = false;
    let attempt = 0;
    let retryTimer: ReturnType<typeof setTimeout> | undefined;

    const connect = async () => {
      setState("connecting");
      try {
        const { ticket } = await api<{ ticket: string }>("/ws-tickets", {
          method: "POST",
          body: { workspace_id: workspaceId },
        });
        if (stopped) return;
        socket = new WebSocket(websocketUrl(ticket));
      } catch {
        scheduleReconnect();
        return;
      }
      socket.onopen = () => {
        if (attempt > 0) handlers.current.onReconnect();
        attempt = 0;
        setState("open");
      };
      socket.onmessage = (message) => {
        const event = JSON.parse(String(message.data)) as RealtimeEvent;
        if (event.type !== "ping") handlers.current.onEvent(event);
      };
      socket.onclose = () => {
        setState("closed");
        scheduleReconnect();
      };
    };

    const scheduleReconnect = () => {
      if (stopped) return;
      attempt += 1;
      const delay = Math.min(MAX_BACKOFF_MS, 500 * 2 ** attempt);
      retryTimer = setTimeout(() => void connect(), delay);
    };

    void connect();
    return () => {
      stopped = true;
      clearTimeout(retryTimer);
      socket?.close();
    };
  }, [workspaceId]);

  return state;
}
