/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        primary: "#FF8DA1",
        secondary: "#FFE066",
        success: "#75D9A5",
        blue: "#7EC8E3",
        dark: "#4A4A4A",
      }
    },
  },
  plugins: [],
}