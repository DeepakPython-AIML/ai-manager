const backend = process.env.BACKEND_URL ?? "http://127.0.0.1:8000";

/** Same-origin proxy, so the browser needs no CORS and the API URL stays server-side. */
export default {
  devIndicators: false,
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${backend}/api/:path*` }];
  },
};
