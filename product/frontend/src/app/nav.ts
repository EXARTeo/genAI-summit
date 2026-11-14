import {
  BookOpenText,
  Boxes,
  BrainCircuit,
  ClipboardCheck,
  Inbox,
  MessagesSquare,
  Settings,
  type LucideIcon,
} from 'lucide-react';

export interface NavItem {
  id: string;
  label: string;
  to: string;
  icon: LucideIcon;
  description: string;
  /** Keyboard shortcut shown in the command palette: "g" then this key. */
  key?: string;
}

/** Sidebar + command palette entries. Badge counts: src/shared/stores/nav.ts. */
export const NAV_ITEMS: NavItem[] = [
  {
    id: 'systems',
    label: 'Systems',
    to: '/systems',
    icon: Boxes,
    description: 'Registered AI systems and their dossiers',
    key: 's',
  },
  {
    id: 'audits',
    label: 'Audits',
    to: '/audits',
    icon: ClipboardCheck,
    description: 'Agent audit runs, findings and reports',
    key: 'a',
  },
  {
    id: 'approvals',
    label: 'Approvals',
    to: '/approvals',
    icon: Inbox,
    description: 'Human-in-the-loop decisions waiting for you',
    key: 'i',
  },
  {
    id: 'regulation',
    label: 'Regulation',
    to: '/regulation',
    icon: BookOpenText,
    description: 'AI Act text, versions and changes',
    key: 'r',
  },
  {
    id: 'memory',
    label: 'Memory',
    to: '/memory',
    icon: BrainCircuit,
    description: 'What the agent learned from your corrections',
    key: 'm',
  },
  { id: 'chat', label: 'Chat', to: '/chat', icon: MessagesSquare, description: 'Ask the copilot', key: 'c' },
];

export const SETTINGS_ITEM: NavItem = {
  id: 'settings',
  label: 'Settings',
  to: '/settings',
  icon: Settings,
  description: 'Theme, API mode and about',
};
