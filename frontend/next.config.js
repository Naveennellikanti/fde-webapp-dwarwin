/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // `standalone` produces the minimal server bundle the Dockerfile copies. Its file
  // tracing step fails on Windows (ENOENT copying manifests), so it is opt-in: the
  // Dockerfile sets NEXT_OUTPUT=standalone, while local `npm run build`/`dev` on any
  // OS uses the default output.
  ...(process.env.NEXT_OUTPUT === 'standalone' ? { output: 'standalone' } : {}),
};

module.exports = nextConfig;
