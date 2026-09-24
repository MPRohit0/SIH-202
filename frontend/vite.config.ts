import {defineConfig} from "vite";
import react from "@vitejs/plugin-react";
import {fileURLToPath} from "node:url";

// Plain Vite + React SPA. Replaces the vinext/Next.js/Cloudflare Workers build
// (see docs/progress.md for why: this app has no server-rendered routes, no
// Cloudflare bindings are required once /api/records is removed, and this is
// the stack CLAUDE.md and docs/handoff_contract.md (CORS allows
// http://localhost:5173) already assume).
export default defineConfig({
  cacheDir: ".vite-cache",
  plugins: [react()],
  resolve: {
    alias: {"@": fileURLToPath(new URL(".", import.meta.url))},
  },
  server: {
    host: "127.0.0.1",
    port: 5173,
  },
  preview: {
    host: "127.0.0.1",
    port: 4173,
  },
});
