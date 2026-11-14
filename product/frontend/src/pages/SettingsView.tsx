import { Monitor, Moon, Sun } from 'lucide-react';
import { useSearchParams } from 'react-router-dom';
import { MemoryBrowser } from '@/features/memory/components/MemoryBrowser';
import { useTheme } from '@/shared/hooks/useTheme';
import { getClientId } from '@/shared/lib/client-id';
import { env } from '@/shared/lib/env';
import { cn } from '@/shared/lib/utils';
import type { ThemePreference } from '@/shared/stores/theme';
import { Badge, Card, KeyValue, PageHeader, PRODUCT_NAME, Tabs } from '@/shared/ui';

const THEMES: { value: ThemePreference; label: string; icon: JSX.Element }[] = [
  { value: 'light', label: 'Light', icon: <Sun /> },
  { value: 'dark', label: 'Dark', icon: <Moon /> },
  { value: 'system', label: 'System', icon: <Monitor /> },
];

const TABS = ['rules', 'appearance', 'connection'] as const;
type Tab = (typeof TABS)[number];

export default function SettingsView() {
  const { preference, setPreference } = useTheme();
  const [params, setParams] = useSearchParams();
  const tab: Tab = TABS.includes(params.get('tab') as Tab) ? (params.get('tab') as Tab) : 'rules';

  return (
    <div>
      <PageHeader
        title="Settings"
        description="Organisation-wide rules the agents follow, appearance and connection."
      />
      <Tabs value={tab} onValueChange={(v) => setParams({ tab: v }, { replace: true })}>
        <Tabs.List>
          <Tabs.Trigger value="rules">Organisation rules</Tabs.Trigger>
          <Tabs.Trigger value="appearance">Appearance</Tabs.Trigger>
          <Tabs.Trigger value="connection">Connection</Tabs.Trigger>
        </Tabs.List>

        <Tabs.Content value="rules">
          <p className="mb-4 max-w-2xl text-sm text-muted">
            Lessons promoted org-wide: every agent applies them in every audit. They start as a correction on
            one system and are promoted by the AI Officer after a regression check.
          </p>
          <MemoryBrowser
            scope="org"
            emptyTitle="No organisation rules yet"
            emptyDescription="Promote a system lesson org-wide from System → Lessons."
          />
        </Tabs.Content>

        <Tabs.Content value="appearance" className="max-w-2xl">
          <Card className="p-5">
            <h2 className="text-sm font-semibold">Theme</h2>
            <p className="text-xs text-muted">Follows your OS by default.</p>
            <div className="mt-4 grid grid-cols-3 gap-2" role="radiogroup" aria-label="Theme">
              {THEMES.map((t) => (
                <button
                  key={t.value}
                  type="button"
                  role="radio"
                  aria-checked={preference === t.value}
                  onClick={() => setPreference(t.value)}
                  className={cn(
                    'flex items-center justify-center gap-2 rounded-lg border px-3 py-2.5 text-sm font-medium transition-colors [&_svg]:size-4',
                    preference === t.value
                      ? 'border-primary/60 bg-primary/5 text-text [&_svg]:text-primary'
                      : 'border-border text-muted hover:border-text/20 hover:text-text',
                  )}
                >
                  {t.icon}
                  {t.label}
                </button>
              ))}
            </div>
          </Card>
        </Tabs.Content>

        <Tabs.Content value="connection" className="max-w-2xl">
          <Card className="p-5">
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
          </Card>
        </Tabs.Content>
      </Tabs>
    </div>
  );
}
