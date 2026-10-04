import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// The Python server serves the built app from src/gs1_scanner/server/static.
// During development, `npm run dev` proxies API calls to `gs1-scanner serve`.
export default defineConfig({
  plugins: [react()],
  build: {
    outDir: "../src/gs1_scanner/server/static",
    emptyOutDir: true,
  },
  server: {
    proxy: { "/api": "http://127.0.0.1:8000" },
  },
});
