import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";

// Proxies /api/* to the FastAPI backend so the frontend never needs to
// know the backend's host/port, and CORS is a non-issue in dev.
// VITE_API_TARGET lets Docker point the proxy at the backend container.
const API_TARGET = process.env.VITE_API_TARGET || "http://localhost:8000";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": {
        target: API_TARGET,
        changeOrigin: true,
        rewrite: (path) => path.replace(/^\/api/, ""),
      },
    },
  },
  test: {
    environment: "jsdom",
    globals: true,
    setupFiles: "./src/test/setup.js",
    css: false,
    coverage: {
      provider: "v8",
      include: ["src/**/*.{js,jsx}"],
      exclude: ["src/**/*.test.*", "src/test/**", "src/__fixtures__/**", "src/main.jsx"],
    },
  },
});
