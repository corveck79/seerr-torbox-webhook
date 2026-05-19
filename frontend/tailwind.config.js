/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        bg: '#0a0e14',
        card: '#141a23',
        border: '#1e2632',
        muted: '#6b7785',
        accent: '#6366f1',
        accent2: '#22d3ee',
        amber: '#fbbf24',
        ok: '#10b981',
      },
    },
  },
  plugins: [],
};
