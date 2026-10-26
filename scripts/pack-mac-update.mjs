#!/usr/bin/env node
/** 生成适合差分更新的 macOS ZIP:app.asar 以 Copy 存储,其他成员正常压缩。 */
import { existsSync } from "node:fs";
import { createRequire } from "node:module";
import { argv, exit } from "node:process";
import { basename, resolve } from "node:path";

const require = createRequire(import.meta.url);
const { archive } = createRequire(require.resolve("electron-builder/package.json"))(
  "app-builder-lib/out/targets/archive.js",
);

function args() {
  const out = {};
  for (let i = 2; i < argv.length; i += 1) {
    const key = argv[i];
    if (!key.startsWith("--")) continue;
    out[key.slice(2)] = argv[i + 1];
    i += 1;
  }
  return out;
}

const options = args();
if (!options.app || !options.out) {
  console.error("usage: node scripts/pack-mac-update.mjs --app path/to/Mosael.app --out path/to/Mosael-VERSION-mac-signed.zip");
  exit(2);
}
const appDir = resolve(options.app);
const outFile = resolve(options.out);
if (!existsSync(appDir) || !existsSync(resolve(appDir, "Contents/Resources/app.asar"))) {
  console.error(`invalid .app or missing Contents/Resources/app.asar: ${appDir}`);
  exit(1);
}

await archive("zip", outFile, appDir, {
  compression: "normal",
  preserveSymlinks: true,
  storedPaths: ["Contents/Resources/app.asar"],
});
console.log(`packed ${basename(outFile)} with app.asar stored for differential updates`);
