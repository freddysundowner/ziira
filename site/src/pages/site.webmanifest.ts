import type { APIRoute } from "astro";
import { siteConfig } from "../lib/siteConfig";

export const GET: APIRoute = () =>
  new Response(
    JSON.stringify({
      name: siteConfig.orgName, short_name: siteConfig.orgName, start_url: "/", display: "browser", background_color: "#f6f7f9", theme_color: "#0f766e",
      icons: [
        { src: "/icon-192.png", sizes: "192x192", type: "image/png" },
        { src: "/icon-512.png", sizes: "512x512", type: "image/png" },
      ],
    }),
    { headers: { "Content-Type": "application/manifest+json" } },
  );
