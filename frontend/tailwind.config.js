/** @type {import('tailwindcss').Config} */
const v = (name) => `rgb(var(--${name}) / <alpha-value>)`
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  darkMode: ['selector', '[data-theme="dark"]'],
  theme: {
    extend: {
      colors: {
        bg: v('bg'), surface: v('surface'), 'surface-2': v('surface-2'), border: v('border'), fg: v('fg'),
        muted: v('muted'), primary: v('primary'), 'primary-fg': v('primary-fg'), danger: v('danger'),
        warning: v('warning'), success: v('success'), info: v('info'),
        'sev-critical': v('sev-critical'), 'sev-high': v('sev-high'), 'sev-medium': v('sev-medium'), 'sev-low': v('sev-low'),
      },
      fontFamily: {
        sans: ['Inter', 'system-ui', '-apple-system', 'Segoe UI', 'Roboto', 'Arial', 'sans-serif'],
        mono: ['JetBrains Mono', 'ui-monospace', 'Menlo', 'Consolas', 'monospace'],
      },
      boxShadow: { card: '0 1px 2px rgb(0 0 0 / 0.12), 0 4px 16px rgb(0 0 0 / 0.08)' },
      keyframes: { 'dash': { to: { strokeDashoffset: '-20' } } },
      animation: { dash: 'dash 0.6s linear infinite' },
    },
  },
  plugins: [],
}
