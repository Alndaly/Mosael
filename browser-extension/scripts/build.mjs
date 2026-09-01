import { cp, mkdir, readFile, rm, writeFile } from "node:fs/promises";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { build } from "esbuild";

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
    sidepanel: resolve(root, "src/sidepanel.ts"),
  },
  outdir,
  bundle: true,
  format: "iife",
  platform: "browser",
  target: "chrome116",
  sourcemap: true,
});

for (const name of ["sidepanel.html", "sidepanel.css"]) {
  await cp(resolve(root, name), resolve(outdir, name));
}
await cp(resolve(repo, "build/icon.png"), resolve(outdir, "icon.png"));

const manifest = JSON.parse(await readFile(resolve(root, "manifest.json"), "utf8"));
const packageJson = JSON.parse(await readFile(resolve(repo, "package.json"), "utf8"));
manifest.version = packageJson.version;
await writeFile(resolve(outdir, "manifest.json"), `${JSON.stringify(manifest, null, 2)}\n`);

console.log(`Built Chrome extension ${manifest.version} → ${outdir}`);
