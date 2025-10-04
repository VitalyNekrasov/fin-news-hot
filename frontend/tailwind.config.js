/** @type {import('tailwindcss').Config} */
export default {
  darkMode: 'class',
  content: ["./index.html","./src/**/*.{ts,tsx}"],
  theme: {
    extend: {
      colors: {
        surface: {
          light: "rgba(255,255,255,0.65)",
          dark: "rgba(24,24,27,0.65)",
        }
      },
      boxShadow: { soft: "0 8px 30px rgba(0,0,0,.06)" },
      borderRadius: { xl2: "1rem" },
    },
  },
  plugins: [],
}
