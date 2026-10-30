/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        ink: { 950: '#0d0d0f', 900: '#131316', 850: '#17171b', 800: '#1c1c21', 750: '#222228', 700: '#2a2a31', 600: '#3a3a43', 500: '#55555f', 400: '#7c7c87', 300: '#a3a3ad', 200: '#cfcfd6', 100: '#ececef' },
        gold: { 500: '#d4a017', 400: '#e2b53a', 300: '#f2c45a' },
        parchment: { 500: '#e8d9b5', 400: '#efe4c9', 300: '#f4ecd9' },
        sepia: '#3a2d1a',
        crimson: '#b3261e',
      },
      fontFamily: {
        ui: ['Inter', 'ui-sans-serif', 'system-ui', 'sans-serif'],
        mono: ['"JetBrains Mono"', 'ui-monospace', 'SFMono-Regular', 'monospace'],
        book: ['Georgia', '"Noto Serif Devanagari"', 'serif'],
      },
      fontSize: { '2xs': ['10.5px', '14px'] },
    },
  },
  plugins: [],
}
