import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";

// The FastAPI backend serves the built app: dist/index.html at the catch-all
// route and dist/assets/* mounted at /assets. During development, `npm run dev`
// proxies /api and the MJPEG streams to the running dashboard on :8765.
export default defineConfig({
  plugins: [react(), tailwindcss()],
  server: {
    proxy: {
      "/api": "http://127.0.0.1:8765",
    },
  },
  build: {
    outDir: "dist",
    emptyOutDir: true,
  },
});
