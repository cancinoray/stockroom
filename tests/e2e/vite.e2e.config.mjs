import { createRequire } from "node:module";
import { fileURLToPath, pathToFileURL } from "node:url";

/**
 * The e2e-only Vite config. It serves the real frontend on a port the e2e run
 * picked, and forwards `/api` to the disposable backend so the app needs no
 * CORS change and no `VITE_API_BASE_URL`.
 *
 * The config lives outside `frontend/`, so bare plugin imports would resolve
 * from this directory and fail. The `createRequire` anchor resolves them from
 * `frontend/package.json` instead — the same node_modules `make install`
 * populated.
 */
const requireFromFrontend = createRequire(
  new URL("../../frontend/package.json", import.meta.url),
);

async function loadPlugin(specifier) {
  const resolved = requireFromFrontend.resolve(specifier);
  const loaded = await import(pathToFileURL(resolved).href);
  return loaded.default;
}

const apiTarget = process.env.E2E_API_TARGET;

if (!apiTarget) {
  throw new Error(
    "E2E_API_TARGET is required: point it at the backend the e2e run started.",
  );
}

const [react, tailwindcss] = await Promise.all([
  loadPlugin("@vitejs/plugin-react"),
  loadPlugin("@tailwindcss/vite"),
]);

export default {
  root: fileURLToPath(new URL("../../frontend", import.meta.url)),
  plugins: [react(), tailwindcss()],
  server: {
    host: "127.0.0.1",
    strictPort: true,
    proxy: {
      "/api": {
        target: apiTarget,
        changeOrigin: true,
      },
    },
  },
};
