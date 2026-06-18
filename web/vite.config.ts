import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Dev: proxy /api to the FastAPI backend (cbtrack serve on :8099) so the
// frontend can use same-origin relative URLs in both dev and production.
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": "http://127.0.0.1:8099",
    },
  },
  build: {
    outDir: "dist",
  },
});
