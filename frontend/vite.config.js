import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/chat": "http://localhost:5000",
      "/jira": "http://localhost:5000",
      "/run-orchestrator": "http://localhost:5000",
    },
  },
});

