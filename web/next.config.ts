import path from "node:path";
import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  turbopack: {
    // There is a stray package-lock.json in C:\Users\DELL. Turbopack walks up
    // looking for a lockfile, finds that one, and roots the project there --
    // which put the HMR socket on the wrong path. Pin the root to this folder.
    root: path.resolve(__dirname),
  },

  // Next blocks its own dev bundles when the page is opened on an origin it
  // does not recognise. Opening the app on 127.0.0.1 rather than localhost was
  // enough to trigger it: the HTML rendered, the client bundle was refused, and
  // the page sat there served but never hydrated -- buttons dead, no errors.
  allowedDevOrigins: ["127.0.0.1", "localhost"],
};

export default nextConfig;
