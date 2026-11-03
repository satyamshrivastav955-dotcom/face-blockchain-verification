import { defineConfig } from "vite";

// Static, dependency-free verifier site. No API, no React: one HTML page + one small script.
// Output: web/dist-verifier/index.html (host the folder anywhere that serves static files over HTTPS).
export default defineConfig({
  root: "verifier",
  base: "./",
  build: {
    outDir: "../dist-verifier",
    emptyOutDir: true,
    target: "es2022",
  },
  server: { host: "127.0.0.1", port: 5174, fs: { allow: [".."] } },
});
