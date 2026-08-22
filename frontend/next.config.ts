import type { NextConfig } from "next";

// THE SAME-ORIGIN PROXY. The browser only ever talks to this frontend;
// every /api/* request is forwarded server-side to the backend. Two
// things this buys, both about cookies: the session cookie is set on and
// sent to ONE origin (no third-party-cookie trouble, no CORS in the
// browser at all), and the backend's real address never appears in
// client code. BACKEND_URL is the one deployment knob.
const backend = process.env.BACKEND_URL ?? "http://localhost:8000";

const nextConfig: NextConfig = {
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${backend}/:path*` }];
  },
};

export default nextConfig;
