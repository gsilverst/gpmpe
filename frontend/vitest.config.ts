import { defineConfig } from "vitest/config";

export default defineConfig({
  cacheDir: "../.test-output/frontend/vite",
  test: {
    environment: "node",
    include: ["tests/**/*.test.ts", "tests/**/*.test.tsx"],
    coverage: {
      reportsDirectory: "../.test-output/frontend/coverage",
    },
  },
});
