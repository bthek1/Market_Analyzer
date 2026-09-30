import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import { TanStackRouterVite } from "@tanstack/router-plugin/vite";
import { fileURLToPath, URL } from "node:url";

export default defineConfig({
  // Config lives in ONE file at the repo root, shared with the backend, docker
  // compose and systemd (issue #4). That file also holds SECRET_KEY and
  // ANTHROPIC_API_KEY, which is safe ONLY because Vite exposes nothing but
  // VITE_-prefixed keys to the bundle: never set `envPrefix` here.
  envDir: fileURLToPath(new URL("..", import.meta.url)),
  plugins: [
    TanStackRouterVite({
      routeFileIgnorePattern: "(test|spec|utils)\\.(ts|tsx)$",
    }),
    react(),
    tailwindcss(),
  ],
  resolve: {
    alias: {
      "@": fileURLToPath(new URL("./src", import.meta.url)),
    },
  },
  server: {
    host: "0.0.0.0",
    port: 5173,
  },
});
