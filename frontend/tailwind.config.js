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
          bg: "#0f0f0f",
          sidebar: "#141414",
          card: "#181818",
          cardHover: "#222222",
          border: "#262626",
          borderLight: "#333333",
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
        sans: ['"IBM Plex Sans"', 'system-ui', '-apple-system', 'sans-serif'],
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
