import { BookOpenText, Boxes, ClipboardCheck, House, MessagesSquare, type LucideIcon } from 'lucide-react';

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
    id: 'home',
    label: 'Home',
    to: '/',
    icon: House,
    description: 'What needs you now: live audits, approvals, findings',
    key: 'h',
  },
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
    description: 'Agent audit runs, findings and reports; the badge counts gates waiting for you',
    key: 'a',
  },
  {
    id: 'regulation',
    label: 'Regulation',
    to: '/regulation',
    icon: BookOpenText,
    description: 'AI Act text, versions and changes',
    key: 'r',
  },
  { id: 'chat', label: 'Chat', to: '/chat', icon: MessagesSquare, description: 'Ask the copilot', key: 'c' },
];
