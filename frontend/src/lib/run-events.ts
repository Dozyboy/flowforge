import type { RealtimeEvent } from "@/lib/types";

type Listener = (event: RealtimeEvent) => void;

/**
 * In-page fan-out of realtime events. The workspace layout owns the single WebSocket and
 * re-emits every event here, so screens like the editor can follow one run's steps live.
 */
class EventBus {
  private listeners = new Set<Listener>();

  emit(event: RealtimeEvent): void {
    this.listeners.forEach((listener) => listener(event));
  }

  subscribe(listener: Listener): () => void {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  }
}

export const liveRunEvents = new EventBus();
