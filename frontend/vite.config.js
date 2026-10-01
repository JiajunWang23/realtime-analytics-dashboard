import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Dev: proxy REST + WebSocket to the Flask backend so the app uses same-origin URLs,
// exactly like production behind nginx / the k8s ingress.
// (macOS reserves :5000 for AirPlay, so start.command runs the backend on :5050.)
const backend = process.env.BACKEND_URL || "http://localhost:5000";

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      "/api": backend,
      "/rta.js": backend,
      "/ws": { target: backend.replace(/^http/, "ws"), ws: true },
    },
  },
});
