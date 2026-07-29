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
          purple: "#5b0e89",
          purpleActive: "#6d10a3",
          purpleLight: "#a855f7",
          purpleBanner: "#4d007d",
          emerald: "#10b981",
          amber: "#f59e0b",
          rose: "#f43f5e",
          cyan: "#06b6d4"
        }
      },
      fontFamily: {
        sans: ['Inter', 'system-ui', '-apple-system', 'BlinkMacSystemFont', 'Segoe UI', 'Roboto', 'sans-serif'],
        mono: ['"JetBrains Mono"', 'Consolas', 'monospace'],
      },
      borderRadius: {
        DEFAULT: '6px',
        'sm': '4px',
        'md': '6px',
        'lg': '8px',
        'xl': '12px',
        'none': '0px'
      }
    },
  },
  plugins: [],
};
