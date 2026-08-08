import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

export default defineConfig({
  plugins: [react()],
  // Without this, /api/... falls through to the SPA index fallback in dev and every
  // request resolves to HTML, so the app reports every call as a failure. The target is
  // the Compose nginx entry point, which strips /api before proxying to the API.
  server: {
    proxy: {
      "/api": {
        target: "http://localhost:3000",
        changeOrigin: true,
      },
    },
  },
  test: {
    environment: "jsdom",
    setupFiles: "./src/test/setup.ts",
    css: true,
  },
});
