import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";
import { fileURLToPath } from "node:url";
import { dirname, resolve } from "node:path";
var here = dirname(fileURLToPath(import.meta.url));
// Dev: this dev server runs on :5173 and proxies /api + /ws back to FastAPI
// on :8800 (see .claude/launch.json's "webapp-dev" entry, and start the
// "admin-portal" server too). Prod: `npm run build` emits ../webapp_dist,
// which admin_portal/main.py serves directly at /app — base: "/app/" makes
// the built asset URLs match that mount point.
//
// TWO entries:
//   index.html  -> the /app SPA (Live Monitoring, camera view, grid, discovery)
//   splash      -> a standalone bundle the server-rendered Jinja pages load,
//                  so the cold-boot splash can play on the portal's real
//                  entry point without dragging the whole router along.
//
// manifest: true so FastAPI can resolve the hashed splash filename instead of
// us pinning an unhashed name and fighting cache staleness.
export default defineConfig({
    base: "/app/",
    plugins: [react()],
    build: {
        outDir: "../webapp_dist",
        emptyOutDir: true,
        manifest: true,
        rollupOptions: {
            input: {
                index: resolve(here, "index.html"),
                splash: resolve(here, "src/splash/mount.tsx"),
            },
        },
    },
    server: {
        port: 5173,
        proxy: {
            "/api": { target: "http://127.0.0.1:8800", changeOrigin: true },
            "/ws": { target: "ws://127.0.0.1:8800", ws: true },
        },
    },
    test: {
        // jsdom for the component/lifecycle tests (rAF cancellation on unmount).
        // The pure-logic suites don't need it but it's harmless for them.
        environment: "jsdom",
    },
});
