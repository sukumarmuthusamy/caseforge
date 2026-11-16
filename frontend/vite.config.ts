import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// During development the UI runs on :5173 and forwards API calls to the Python
// server on :8000. In production the Python server serves the built files itself.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: { "/api": "http://127.0.0.1:8000" },
  },
  build: { outDir: "dist", chunkSizeWarningLimit: 900 },
});
