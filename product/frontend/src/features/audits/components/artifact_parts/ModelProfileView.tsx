import { AlertTriangle } from 'lucide-react';
import { Bar, BarChart, Cell, ResponsiveContainer, Tooltip as RTooltip, XAxis, YAxis } from 'recharts';
import { Badge, KeyValue } from '@/shared/ui';
import type { ModelProfileData } from '../../lib/types';
import { SimpleTable, SubHeading } from './common';

const NEUTRAL = 'rgb(var(--rgb-text) / 0.22)';
const WARN = 'rgb(var(--rgb-warning))';
const MUTED = 'rgb(var(--rgb-muted))';

/** Feature sensitivity (one series, sorted) with protected proxies flagged in amber + icon. */
export function ModelProfileView({ data }: { data: ModelProfileData }) {
  const rows = [...data.sensitivity].sort((a, b) => b.score - a.score);
  return (
    <div>
      <KeyValue
        columns={3}
        items={[
          { label: 'Model', value: `${data.model.name} v${data.model.version}`, mono: true },
          { label: 'Flavor', value: data.model.flavor },
          { label: 'Probes', value: data.probes.toLocaleString() },
          ...Object.entries(data.model.metrics).map(([k, v]) => ({
            label: k.toUpperCase(),
            value: v.toFixed(2),
            mono: true,
          })),
        ]}
      />

      <SubHeading
        right={
          <Badge tone="warning" icon={<AlertTriangle />}>
            protected proxy
          </Badge>
        }
      >
        Feature sensitivity
      </SubHeading>
      <p className="-mt-1 mb-2 text-xs text-muted">
        How much the score moves when each feature is perturbed. Amber = a known proxy for a protected
        attribute.
      </p>
      <div className="h-64 w-full" role="img" aria-label="Feature sensitivity bar chart">
        <ResponsiveContainer>
          <BarChart
            data={rows}
            layout="vertical"
            margin={{ left: 8, right: 32, top: 4, bottom: 4 }}
            barCategoryGap={6}
          >
            <XAxis
              type="number"
              domain={[0, 'dataMax']}
              hide
              tick={{ fill: MUTED, fontSize: 11 }}
              axisLine={false}
              tickLine={false}
            />
            <YAxis
              type="category"
              dataKey="feature"
              width={180}
              tick={({ x, y, payload }) => {
                const r = rows.find((f) => f.feature === payload.value);
                return (
                  <text
                    x={x}
                    y={y}
                    dy={4}
                    textAnchor="end"
                    fontSize={12}
                    fill={r?.protectedProxy ? WARN : 'rgb(var(--rgb-text))'}
                    style={{ fontFamily: "'JetBrains Mono Variable', ui-monospace, monospace" }}
                  >
                    {r?.protectedProxy ? '⚠ ' : ''}
                    {payload.value}
                  </text>
                );
              }}
              axisLine={false}
              tickLine={false}
            />
            <RTooltip
              cursor={{ fill: 'rgb(var(--rgb-text) / 0.04)' }}
              contentStyle={{
                background: 'rgb(var(--rgb-surface))',
                border: '1px solid rgb(var(--rgb-border))',
                borderRadius: 8,
                fontSize: 12,
              }}
              formatter={(v: number, _n, p) => [
                v.toFixed(2),
                (p.payload as { note?: string }).note ?? 'sensitivity',
              ]}
            />
            <Bar
              dataKey="score"
              radius={[0, 3, 3, 0]}
              barSize={14}
              isAnimationActive
              animationDuration={700}
              label={{ position: 'right', fill: MUTED, fontSize: 11, formatter: (v: number) => v.toFixed(2) }}
            >
              {rows.map((r) => (
                <Cell key={r.feature} fill={r.protectedProxy && r.score >= 0.05 ? WARN : NEUTRAL} />
              ))}
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>

      <SubHeading>Decision boundaries</SubHeading>
      <SimpleTable
        head={['Feature', 'Boundary', 'Flip rate', 'Note']}
        rows={data.boundary.map((b) => [
          <span className="font-mono text-xs">{b.feature}</span>,
          b.threshold,
          <span className={b.flipRate >= 0.15 ? 'font-semibold text-danger' : ''}>
            {Math.round(b.flipRate * 100)}%
          </span>,
          <span className="text-muted">{b.note}</span>,
        ])}
      />

      {data.notes.length > 0 && (
        <>
          <SubHeading>Agent notes</SubHeading>
          <ul className="list-disc space-y-1 pl-5 text-sm">
            {data.notes.map((n) => (
              <li key={n}>{n}</li>
            ))}
          </ul>
        </>
      )}
    </div>
  );
}
