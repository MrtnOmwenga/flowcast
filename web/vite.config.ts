import { defineConfig } from "vite";

// In development the service runs separately on port 8000.
export default defineConfig({
  build: { target: "es2022", chunkSizeWarningLimit: 800 },
  server: { proxy: { "/api": "http://localhost:8000" } },
  preview: { proxy: { "/api": "http://localhost:8000" } },
});
