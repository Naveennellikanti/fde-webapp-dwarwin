/** @type {import('tailwindcss').Config} */
module.exports = {
  content: [
    './app/**/*.{js,ts,jsx,tsx,mdx}',
    './components/**/*.{js,ts,jsx,tsx,mdx}',
    './lib/**/*.{js,ts,jsx,tsx,mdx}',
  ],
  theme: {
    extend: {
      fontFamily: {
        sans: ['var(--font-sans)', 'ui-sans-serif', 'system-ui', 'sans-serif'],
        mono: ['var(--font-mono)', 'ui-monospace', 'SFMono-Regular', 'Menlo', 'Consolas', 'monospace'],
      },
      // A small, deliberate type scale. Headings carry negative tracking because at
      // semibold weight the default spacing reads loose; small text gets positive
      // tracking so 11px labels stay legible.
      fontSize: {
        'label': ['0.6875rem', { lineHeight: '1rem', letterSpacing: '0.04em' }],   // 11px
        'meta': ['0.75rem', { lineHeight: '1.125rem', letterSpacing: '0.01em' }],  // 12px
        'body': ['0.875rem', { lineHeight: '1.5rem' }],                            // 14px
        'title': ['0.9375rem', { lineHeight: '1.375rem', letterSpacing: '-0.01em' }],
        'display': ['1.375rem', { lineHeight: '1.75rem', letterSpacing: '-0.021em' }],
      },
      colors: {
        accent: {
          50: '#eef2ff',
          100: '#e0e7ff',
          200: '#c7d2fe',
          300: '#a5b4fc',
          400: '#818cf8',
          500: '#6366f1',
          600: '#4f46e5',
          700: '#4338ca',
          800: '#3730a3',
          900: '#312e81',
        },
      },
      boxShadow: {
        card: '0 1px 2px 0 rgb(15 23 42 / 0.04), 0 1px 3px 0 rgb(15 23 42 / 0.06)',
        lift: '0 4px 12px -2px rgb(15 23 42 / 0.08), 0 2px 4px -2px rgb(15 23 42 / 0.06)',
      },
      keyframes: {
        'fade-up': {
          '0%': { opacity: '0', transform: 'translateY(6px)' },
          '100%': { opacity: '1', transform: 'translateY(0)' },
        },
      },
      animation: {
        'fade-up': 'fade-up 0.24s ease-out both',
      },
    },
  },
  plugins: [],
};
