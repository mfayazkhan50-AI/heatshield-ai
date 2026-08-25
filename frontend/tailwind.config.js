/** @type {import('tailwindcss').Config} */
module.exports = {
  content: [
    "./src/app/**/*.{js,ts,jsx,tsx,mdx}",
    "./src/components/**/*.{js,ts,jsx,tsx,mdx}",
    "./src/hooks/**/*.{js,ts,jsx,tsx}",
    "./src/lib/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      colors: {
        // Base surfaces — Vercel/Linear-grade near-black console
        void: "#0A0D0F",
        panel: "#12171A",
        "panel-raised": "#1A2226",
        hairline: "#26312F",

        // Thermal scale — the signature gradient (cool -> critical)
        thermal: {
          low: "#3B82F6",      // safety blue
          caution: "#EAB308",  // amber
          warning: "#F59E0B",  // deep amber
          danger: "#EF4444",   // red
          extreme: "#B91C1C",  // dark red / critical
        },

        // Brand status propagation — logo + card borders follow live risk
        brand: {
          normal:   "#22C55E", // green
          elevated: "#F59E0B", // amber
          high:     "#F97316", // orange
          critical: "#DC2626", // crimson
        },

        ink: {
          primary: "#E7ECEA",
          secondary: "#8FA098",
          muted: "#5C6B65",
        },
      },
      fontFamily: {
        // Self-contained system stacks — no network font fetch at build/dev
        // time, so the app builds and runs fully offline.
        display: [
          "system-ui",
          "-apple-system",
          "Segoe UI Variable Display",
          "Segoe UI",
          "sans-serif",
        ],
        body: [
          "system-ui",
          "-apple-system",
          "Segoe UI Variable Text",
          "Segoe UI",
          "Roboto",
          "sans-serif",
        ],
        mono: [
          "Cascadia Code",
          "Consolas",
          "SFMono-Regular",
          "Menlo",
          "ui-monospace",
          "monospace",
        ],
      },
      backgroundImage: {
        "thermal-gradient": "linear-gradient(90deg, #3B82F6 0%, #EAB308 45%, #F59E0B 65%, #EF4444 85%, #B91C1C 100%)",
        "grid-overlay": "linear-gradient(rgba(38,49,47,0.35) 1px, transparent 1px), linear-gradient(90deg, rgba(38,49,47,0.35) 1px, transparent 1px)",
      },
      backgroundSize: {
        grid: "28px 28px",
      },
      boxShadow: {
        glow: "0 0 24px -4px rgba(245, 158, 11, 0.35)",
      },
      keyframes: {
        pulse_soft: {
          "0%, 100%": { opacity: 1 },
          "50%": { opacity: 0.55 },
        },
        scan: {
          "0%": { transform: "translateY(-100%)" },
          "100%": { transform: "translateY(100%)" },
        },
        banner_sweep: {
          "0%": { backgroundPosition: "-200% 0" },
          "100%": { backgroundPosition: "200% 0" },
        },
      },
      animation: {
        pulse_soft: "pulse_soft 2s ease-in-out infinite",
        scan: "scan 3s linear infinite",
        banner_sweep: "banner_sweep 2.4s linear infinite",
      },
    },
  },
  plugins: [],
};
