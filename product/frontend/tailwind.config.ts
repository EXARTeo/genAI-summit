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
      // Radii: 6 (controls), 8 (lg: buttons, inputs), 10 (xl: cards), 12 (2xl: dialogs, sheets).
      borderRadius: { md: '0.375rem', lg: '0.5rem', xl: '0.625rem', '2xl': '0.75rem' },
      fontSize: {
        '2xs': ['11px', { lineHeight: '16px' }],
        xs: ['12px', { lineHeight: '16px' }],
        sm: ['13px', { lineHeight: '20px' }],
        base: ['14px', { lineHeight: '22px' }],
        lg: ['16px', { lineHeight: '24px', letterSpacing: '-0.01em' }],
        xl: ['18px', { lineHeight: '26px', letterSpacing: '-0.015em' }],
        '2xl': ['22px', { lineHeight: '28px', letterSpacing: '-0.02em' }],
        '3xl': ['28px', { lineHeight: '34px', letterSpacing: '-0.025em' }],
      },
      maxWidth: { content: 'var(--content-max)' },
      boxShadow: {
        card: 'var(--shadow-soft)',
        lift: 'var(--shadow-pop)',
        pop: 'var(--shadow-pop)',
        glow: 'var(--shadow-pop)',
      },
      transitionTimingFunction: { 'out-expo': 'cubic-bezier(0.16, 1, 0.3, 1)' },
    },
  },
  plugins: [],
};

export default config;
