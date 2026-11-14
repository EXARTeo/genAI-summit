import type { Config } from 'tailwindcss';

// Tailwind reads ONLY CSS variables (src/styles/theme/*). Colours come from
// branding/brand.json via the generated tokens.css -> semantic.css; radii and shadows
// from shape.css; shell/component colours from components.css.
// Never hard-code hex, rgb or Tailwind palette colours (zinc, white, black...) here or in components.
const channel = (name: string) => `rgb(var(--${name}) / <alpha-value>)`;

const config: Config = {
  darkMode: ['class', '[data-theme="dark"]'],
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    container: { center: true, padding: '1rem' },
    extend: {
      colors: {
        background: channel('background'),
        foreground: channel('foreground'),
        surface: {
          DEFAULT: channel('surface'),
          raised: channel('surface-raised'),
          sunken: channel('surface-sunken'),
          // Legacy alias of `sunken`.
          muted: channel('surface-sunken'),
        },
        text: channel('foreground'),
        muted: channel('muted-foreground'),
        border: channel('border'),
        ring: channel('ring'),
        primary: { DEFAULT: channel('primary'), foreground: channel('primary-foreground') },
        accent: { DEFAULT: channel('accent'), foreground: channel('accent-foreground') },
        success: { DEFAULT: channel('success'), foreground: channel('success-foreground') },
        warning: { DEFAULT: channel('warning'), foreground: channel('warning-foreground') },
        danger: { DEFAULT: channel('danger'), foreground: channel('danger-foreground') },
        info: { DEFAULT: channel('info'), foreground: channel('info-foreground') },
        chart: {
          1: channel('chart-1'),
          2: channel('chart-2'),
          3: channel('chart-3'),
          4: channel('chart-4'),
          5: channel('chart-5'),
        },
        // Full colours (no opacity modifier): component vars from theme/components.css.
        hover: { DEFAULT: 'var(--hover-surface)', strong: 'var(--hover-surface-strong)' },
        shell: { frame: 'var(--shell-frame)', card: 'var(--shell-card)' },
        topbar: 'var(--topbar-bg)',
        scrim: { DEFAULT: 'var(--scrim)', strong: 'var(--scrim-strong)' },
        'switch-thumb': 'var(--switch-thumb)',
        'nav-active': 'var(--nav-active-bg)',
      },
      fontFamily: {
        sans: ['var(--font-body)', 'Inter Variable', 'Inter', 'system-ui', 'sans-serif'],
        heading: ['var(--font-heading)', 'EB Garamond Variable', 'Georgia', 'serif'],
        mono: ['var(--font-mono)', 'JetBrains Mono Variable', 'ui-monospace', 'monospace'],
      },
      borderRadius: {
        sm: 'var(--radius-sm)',
        md: 'var(--radius-md)',
        lg: 'var(--radius-lg)',
        xl: 'var(--radius-xl)',
        '2xl': 'var(--radius-2xl)',
        shell: 'var(--shell-card-radius)',
      },
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
      // Bare `border` / preflight default: the brand border, not Tailwind's gray-200.
      borderColor: { DEFAULT: channel('border') },
      ringColor: { DEFAULT: channel('ring') },
      maxWidth: { content: 'var(--content-max)' },
      width: { sidebar: 'var(--sidebar-width)', 'sidebar-collapsed': 'var(--sidebar-width-collapsed)' },
      height: { topbar: 'var(--topbar-height)' },
      boxShadow: {
        sm: 'var(--shadow-sm)',
        card: 'var(--shadow-soft)',
        lift: 'var(--shadow-pop)',
        pop: 'var(--shadow-pop)',
        glow: 'var(--shadow-pop)',
        shell: 'var(--shell-card-shadow)',
      },
      transitionTimingFunction: { 'out-expo': 'var(--ease-out)' },
    },
  },
  plugins: [],
};

export default config;
