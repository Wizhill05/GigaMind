/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        render: {
          bg: "#0a0b0e",
          sidebar: "#0f1015",
          card: "#13151c",
          cardHover: "#181a24",
          border: "#1e2029",
          borderLight: "#262936",
          textMuted: "#8a8f9e",
          textSecondary: "#c1c5d0",
          textPrimary: "#f4f5f8",
          orange: "#ff6b00",
          orangeHover: "#e05e00",
          orangeLight: "#ff8800",
          amber: "#f59e0b",
          amberLight: "#fbbf24",
          emerald: "#10b981",
          rose: "#f43f5e",
          cyan: "#06b6d4"
        }
      },
      fontFamily: {
        sans: ['Lexend', 'system-ui', '-apple-system', 'sans-serif'],
        mono: ['"JetBrains Mono"', 'Consolas', 'monospace'],
      },
      borderRadius: {
        DEFAULT: '2px',
        'sm': '2px',
        'md': '2px',
        'lg': '2px',
        'xl': '2px',
        'none': '0px'
      }
    },
  },
  plugins: [],
};
