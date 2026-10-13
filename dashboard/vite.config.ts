import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { resolve } from "path";

export default defineConfig({
  plugins: [react()],
  publicDir: "public",
  resolve: {
    alias: {
      "@": resolve(__dirname, "src"),
    },
  },
});
