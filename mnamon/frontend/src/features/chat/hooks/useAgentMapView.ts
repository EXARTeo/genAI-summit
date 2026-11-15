import { useCallback, useState } from 'react';

/**
 * How the agent map draws the conversation's sub-agents: the indented tree or the top-down flow
 * graph (port of magenticx `useAgentMapView`). Remembered per browser; the tree by default and
 * whenever storage is unavailable.
 */
export type AgentMapViewMode = 'tree' | 'flow';

export const AGENT_MAP_VIEW_KEY = 'mnamon_agent_map_view';

export function loadAgentMapView(): AgentMapViewMode {
  try {
    return localStorage.getItem(AGENT_MAP_VIEW_KEY) === 'flow' ? 'flow' : 'tree';
  } catch {
    return 'tree';
  }
}

export function saveAgentMapView(mode: AgentMapViewMode): void {
  try {
    localStorage.setItem(AGENT_MAP_VIEW_KEY, mode);
  } catch {
    // Storage unavailable: the choice still holds for this document.
  }
}

/** The remembered view, and a setter that remembers the next one. */
export function useAgentMapView(): [AgentMapViewMode, (mode: AgentMapViewMode) => void] {
  const [mode, setMode] = useState<AgentMapViewMode>(loadAgentMapView);
  const change = useCallback((next: AgentMapViewMode) => {
    setMode(next);
    saveAgentMapView(next);
  }, []);
  return [mode, change];
}
