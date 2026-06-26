import type { NextConfig } from "next";
import path from "path";
import { withSentryConfig } from "@sentry/nextjs";

const nextConfig: NextConfig = {
  output: "standalone",
  outputFileTracingRoot: path.join(__dirname),
};

export default withSentryConfig(nextConfig, {
  silent: true,
  // `disableLogger` was renamed to `webpack.treeshake.removeDebugLogging`.
  // It's webpack-only (a no-op under Turbopack, which we use for dev) but it
  // silences the deprecation warning and still strips Sentry debug logging
  // from webpack production builds.
  webpack: {
    treeshake: {
      removeDebugLogging: true,
    },
  },
});
