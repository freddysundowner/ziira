// Regenerates the PNG icons from public/favicon.svg (run once; the PNGs are committed): node scripts/make-icons.mjs
import sharp from "sharp";
import fs from "node:fs";
const svg = fs.readFileSync(new URL("../public/favicon.svg", import.meta.url));
const out = (n) => new URL(`../public/${n}`, import.meta.url).pathname;
await sharp(svg, { density: 600 }).resize(32, 32).png().toFile(out("favicon-32.png"));
await sharp(svg, { density: 600 }).resize(180, 180).png().toFile(out("apple-touch-icon.png"));
await sharp(svg, { density: 600 }).resize(192, 192).png().toFile(out("icon-192.png"));
await sharp(svg, { density: 600 }).resize(512, 512).png().toFile(out("icon-512.png"));
console.log("icons written");
