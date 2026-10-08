import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // A self-contained server (web/Dockerfile): no node_modules in the image.
  output: "standalone",
  cacheComponents: true,
  partialPrefetching: true,
  turbopack: {
    rules: {
      "*.css": {
        loaders: ["@tailwindcss/turbopack"],
        as: "*.css",
      },
    },
  },
};

export default nextConfig;
