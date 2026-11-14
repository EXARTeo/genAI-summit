import type { Config } from 'tailwindcss';

// Colours come from branding/brand.json via src/styles/theme/tokens.css (generated).
// Never hard-code brand hex values here or in components.
const token = (name: string) => `rgb(var(--rgb-${name}) / <alpha-value>)`;

const config: Config = {
  darkMode: ['class', '[data-theme="dark"]'],
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    container: { center: true, padding: '1rem' },
    extend: {
      colors: {
        background: token('background'),
        surface: { DEFAULT: token('surface'), muted: token('surface-muted') },
        text: token('text'),
        muted: token('muted'),
        border: token('border'),
        ring: token('ring'),
        primary: { DEFAULT: token('primary'), foreground: token('primary-foreground') },
        accent: { DEFAULT: token('accent'), foreground: token('accent-foreground') },
        success: token('success'),
        warning: { DEFAULT: token('warning'), foreground: token('warning-foreground') },
        danger: token('danger'),
        info: token('info'),
      },
      fontFamily: {
        sans: ['var(--font-body)', 'Inter Variable', 'Inter', 'system-ui', 'sans-serif'],
        heading: ['var(--font-heading)', 'Inter Variable', 'Inter', 'system-ui', 'sans-serif'],
        mono: ['var(--font-mono)', 'JetBrains Mono Variable', 'ui-monospace', 'monospace'],
      },
      borderRadius: { lg: '0.75rem', xl: '1rem', '2xl': '1.25rem' },
      boxShadow: {
        card: '0 1px 2px rgb(var(--rgb-text) / 0.04), 0 4px 16px -4px rgb(var(--rgb-text) / 0.08)',
        lift: '0 2px 4px rgb(var(--rgb-text) / 0.05), 0 14px 32px -8px rgb(var(--rgb-text) / 0.18)',
        glow: '0 0 0 1px rgb(var(--rgb-primary) / 0.25), 0 8px 32px -6px rgb(var(--rgb-primary) / 0.45)',
      },
      transitionTimingFunction: { 'out-expo': 'cubic-bezier(0.16, 1, 0.3, 1)' },
    },
  },
  plugins: [],
};

export default config;
