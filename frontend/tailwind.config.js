/** @type {import('tailwindcss').Config} */
const token = (name) => `rgb(var(--${name}) / <alpha-value>)`;

// Colours are CSS variables (src/index.css) so light and dark themes, and the brand, change in one place.
export default {
  content: ["./index.html", "./src/**/*.{ts,tsx}"],
  darkMode: "class",
  theme: {
    extend: {
      fontFamily: { sans: ["Inter", "ui-sans-serif", "system-ui", "-apple-system", "Segoe UI", "Roboto", "sans-serif"] },
      colors: {
        bg: token("bg"),
        surface: token("surface"),
        sunken: token("sunken"),
        line: token("line"),
        ink: token("ink"),
        muted: token("muted"),
        brand: { DEFAULT: token("brand"), strong: token("brand-strong"), soft: token("brand-soft"), ink: token("brand-ink") },
        ok: { DEFAULT: token("ok"), soft: token("ok-soft") },
        warn: { DEFAULT: token("warn"), soft: token("warn-soft") },
        bad: { DEFAULT: token("bad"), soft: token("bad-soft") },
        info: { DEFAULT: token("info"), soft: token("info-soft") },
      },
      boxShadow: {
        card: "0 1px 2px rgb(var(--shadow) / 0.06), 0 1px 1px rgb(var(--shadow) / 0.04)",
        pop: "0 12px 32px rgb(var(--shadow) / 0.18), 0 2px 6px rgb(var(--shadow) / 0.08)",
      },
      keyframes: {
        fade: { from: { opacity: "0" }, to: { opacity: "1" } },
        rise: { from: { opacity: "0", transform: "translateY(8px) scale(.98)" }, to: { opacity: "1", transform: "none" } },
        slide: { from: { transform: "translateX(100%)" }, to: { transform: "none" } },
        slideleft: { from: { transform: "translateX(-100%)" }, to: { transform: "none" } },
        pulse2: { "0%,100%": { opacity: "1" }, "50%": { opacity: ".45" } },
      },
      animation: { fade: "fade .15s ease-out", rise: "rise .18s ease-out", slide: "slide .22s ease-out", slideleft: "slideleft .22s ease-out", pulse2: "pulse2 1.4s ease-in-out infinite" },
    },
  },
  plugins: [],
};
