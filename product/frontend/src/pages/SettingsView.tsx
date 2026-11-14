import { Monitor, Moon, Settings, Sun } from 'lucide-react';
import { useTheme } from '@/shared/hooks/useTheme';
import { getClientId } from '@/shared/lib/client-id';
import { env } from '@/shared/lib/env';
import { cn } from '@/shared/lib/utils';
import type { ThemePreference } from '@/shared/stores/theme';
import { Badge, Card, CardContent, CardHeader, KeyValue, PageHeader, PRODUCT_NAME } from '@/shared/ui';

const THEMES: { value: ThemePreference; label: string; icon: JSX.Element }[] = [
  { value: 'light', label: 'Light', icon: <Sun /> },
  { value: 'dark', label: 'Dark', icon: <Moon /> },
  { value: 'system', label: 'System', icon: <Monitor /> },
];

export default function SettingsView() {
  const { preference, setPreference } = useTheme();
  return (
    <div className="max-w-3xl space-y-6">
      <PageHeader title="Settings" description="Appearance and connection details." icon={<Settings />} />
      <Card>
        <CardHeader title="Appearance" description="Follows your OS by default." />
        <CardContent>
          <div className="grid grid-cols-3 gap-3" role="radiogroup" aria-label="Theme">
            {THEMES.map((t) => (
              <button
                key={t.value}
                type="button"
                role="radio"
                aria-checked={preference === t.value}
                onClick={() => setPreference(t.value)}
                className={cn(
                  'flex flex-col items-center gap-2 rounded-xl border p-4 text-sm font-medium transition-all [&_svg]:size-5',
                  preference === t.value
                    ? 'border-primary bg-primary/5 text-primary shadow-glow'
                    : 'border-border hover:border-primary/40',
                )}
              >
                {t.icon}
                {t.label}
              </button>
            ))}
          </div>
        </CardContent>
      </Card>
      <Card>
        <CardHeader title="Connection" />
        <CardContent>
          <KeyValue
            items={[
              { label: 'Product', value: PRODUCT_NAME },
              {
                label: 'API mode',
                value: env.useMocks ? (
                  <Badge tone="warning">Mock data</Badge>
                ) : (
                  <Badge tone="success">Live backend</Badge>
                ),
              },
              { label: 'API base', value: env.apiBase, mono: true },
              {
                label: 'Client id',
                value: getClientId(),
                mono: true,
                hint: 'Anonymous browser id sent as X-Client-Id. Not a login.',
              },
            ]}
          />
        </CardContent>
      </Card>
    </div>
  );
}
