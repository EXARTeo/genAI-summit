import { Monitor, Moon, Sun } from 'lucide-react';
import { useTheme } from '@/shared/hooks/useTheme';
import type { ThemePreference } from '@/shared/stores/theme';
import { DropdownMenu, IconButton } from '@/shared/ui';

const OPTIONS: { value: ThemePreference; label: string; icon: JSX.Element }[] = [
  { value: 'light', label: 'Light', icon: <Sun /> },
  { value: 'dark', label: 'Dark', icon: <Moon /> },
  { value: 'system', label: 'System', icon: <Monitor /> },
];

export function ThemeToggle() {
  const { preference, resolved, setPreference } = useTheme();
  return (
    <DropdownMenu
      trigger={
        <IconButton
          label={`Theme: ${preference}`}
          tooltip={false}
          icon={resolved === 'dark' ? <Moon /> : <Sun />}
          data-testid="theme-toggle"
        />
      }
      items={OPTIONS.map((o) => ({
        label: o.label,
        icon: o.icon,
        checked: preference === o.value,
        onSelect: () => setPreference(o.value),
      }))}
    />
  );
}
