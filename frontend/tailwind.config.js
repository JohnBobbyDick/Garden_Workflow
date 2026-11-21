/** @type {import('tailwindcss').Config} */
const v = (name) => `rgb(var(--${name}) / <alpha-value>)`
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  darkMode: ['selector', '[data-theme="dark"]'],
  theme: {
    extend: {
      colors: {
        bg: v('bg'), surface: v('surface'), 'surface-2': v('surface-2'), border: v('border'), fg: v('fg'),
        muted: v('muted'), primary: v('primary'), 'primary-fg': v('primary-fg'), danger: v('danger'), soft: v('soft'),
        'score-bg': v('score-bg'), 'danger-soft': v('danger-soft'), 'warning-soft': v('warning-soft'), edge: v('edge'), grid: v('grid'),
        warning: v('warning'), success: v('success'), info: v('info'),
        'sev-critical': v('sev-critical'), 'sev-high': v('sev-high'), 'sev-medium': v('sev-medium'), 'sev-low': v('sev-low'),
      },
      fontFamily: {
        sans: ['Inter', 'system-ui', '-apple-system', 'Segoe UI', 'Roboto', 'Arial', 'sans-serif'],
        mono: ['JetBrains Mono', 'ui-monospace', 'Menlo', 'Consolas', 'monospace'],
      },
      boxShadow: { card: 'none', pop: '0 8px 24px rgb(32 39 34 / 0.12)' },
      borderRadius: { card: '15px', chip: '9px', field: '8px' },
      fontSize: { display: ['48px', { lineHeight: '58px', fontWeight: '700' }], num: ['34px', '41px'], score: ['66px', '80px'] },
      keyframes: { 'dash': { to: { strokeDashoffset: '-20' } } },
      animation: { dash: 'dash 0.6s linear infinite' },
    },
  },
  plugins: [],
}
