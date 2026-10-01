import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Dev: proxy REST + WebSocket to the Flask backend so the app uses same-origin URLs,
// exactly like production behind nginx / the k8s ingress.
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      "/api": "http://localhost:5000",
      "/ws": { target: "ws://localhost:5000", ws: true },
    },
  },
});
