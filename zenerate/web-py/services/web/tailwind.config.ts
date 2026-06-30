import type { Config } from "tailwindcss";

const config: Config = {
  content: [
    "./pages/**/*.{js,ts,jsx,tsx,mdx}",
    "./components/**/*.{js,ts,jsx,tsx,mdx}",
    "./app/**/*.{js,ts,jsx,tsx,mdx}",
  ],
  theme: {
    extend: {
      fontFamily: {
        sans: ["Instrument Sans", "ui-sans-serif", "system-ui", "sans-serif"],
        mono: ["Geist Mono", "ui-monospace", "monospace"],
      },
      colors: {
        bg:      "#f6f6f5",
        surface: { DEFAULT: "#ffffff", 2: "#fafafa", 3: "#f4f4f3" },
        border:  { DEFAULT: "#e4e4e3", strong: "#d0d0ce" },
        ink:     { DEFAULT: "#1a1a1a", 2: "#555554", 3: "#9d9d9b" },
        blue:    { DEFAULT: "#2563eb", bg: "#eff6ff", bd: "#bfdbfe" },
        pass:    { DEFAULT: "#16a34a", bg: "#f0fdf4" },
        fail:    { DEFAULT: "#dc2626", bg: "#fff1f0" },
        warn:    { DEFAULT: "#d97706", bg: "#fffbeb" },
      },
      boxShadow: {
        sm:  "0 1px 2px rgba(0,0,0,0.05)",
        md:  "0 2px 8px rgba(0,0,0,0.07), 0 0 0 1px rgba(0,0,0,0.04)",
        lg:  "0 8px 24px rgba(0,0,0,0.10), 0 0 0 1px rgba(0,0,0,0.04)",
        overlay: "0 20px 60px rgba(0,0,0,0.18), 0 0 0 1px rgba(0,0,0,0.06)",
      },
    },
  },
  plugins: [],
};

export default config;
