import { cp, mkdir, readFile, rm, writeFile } from "node:fs/promises";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { build } from "esbuild";
import postcss from "postcss";
import tailwindcss from "@tailwindcss/postcss";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const repo = resolve(root, "..");
const outdir = resolve(root, "dist");

await rm(outdir, { recursive: true, force: true });
await mkdir(outdir, { recursive: true });
await build({
  entryPoints: {
    background: resolve(root, "src/background.ts"),
    content: resolve(root, "src/content.ts"),
    "page-bridge": resolve(root, "src/page-bridge.ts"),
    sidepanel: resolve(root, "src/sidepanel.tsx"),
  },
  outdir,
  bundle: true,
  format: "iife",
  platform: "browser",
  target: "chrome116",
  jsx: "automatic",
  minify: true,
  sourcemap: true,
});

const sourceCss = await readFile(resolve(root, "src/styles.css"), "utf8");
const compiledCss = await postcss([tailwindcss()]).process(sourceCss, {
  from: resolve(root, "src/styles.css"),
  to: resolve(outdir, "sidepanel.css"),
});
await writeFile(resolve(outdir, "sidepanel.css"), compiledCss.css);
await cp(resolve(root, "sidepanel.html"), resolve(outdir, "sidepanel.html"));
await cp(resolve(root, "_locales"), resolve(outdir, "_locales"), { recursive: true });
await cp(resolve(repo, "build/icon.png"), resolve(outdir, "icon.png"));
await cp(resolve(repo, "brand/mosael-icon-light.png"), resolve(outdir, "mosael-icon-light.png"));
await cp(resolve(repo, "brand/mosael-icon-dark.png"), resolve(outdir, "mosael-icon-dark.png"));

const manifest = JSON.parse(await readFile(resolve(root, "manifest.json"), "utf8"));
const packageJson = JSON.parse(await readFile(resolve(repo, "package.json"), "utf8"));
manifest.version = packageJson.version;
await writeFile(resolve(outdir, "manifest.json"), `${JSON.stringify(manifest, null, 2)}\n`);

console.log(`Built Chrome extension ${manifest.version} → ${outdir}`);
