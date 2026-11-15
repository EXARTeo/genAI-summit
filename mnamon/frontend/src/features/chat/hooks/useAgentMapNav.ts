/**
 * "Open this task in the agent map" from anywhere in the chat (a task marker, a task card): the
 * marker asks, the agent map button opens its panel on that task's detail (magenticx
 * `useBackgroundTasksContext().openTask`).
 */
import { create } from 'zustand';

export interface AgentMapRequest {
  taskId: string;
  /** Changes on every request, so asking for the same task twice opens it twice. */
  nonce: number;
}

interface AgentMapNav {
  request: AgentMapRequest | null;
  openTask: (taskId: string) => void;
  clear: () => void;
}

export const useAgentMapNav = create<AgentMapNav>((set) => ({
  request: null,
  openTask: (taskId) => set((s) => ({ request: { taskId, nonce: (s.request?.nonce ?? 0) + 1 } })),
  clear: () => set({ request: null }),
}));
