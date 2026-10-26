import assert from "node:assert/strict";
import test from "node:test";

import { renderDownloadPage } from "../scripts/r2-download-page.mjs";

test("R2 下载页只链接这次真实存在的安装产物", () => {
  const html = renderDownloadPage([
    "Mosael-2.2.3-arm64.dmg",
    "Mosael Setup 2.2.3.exe",
    "Mosael-2.2.3-mac-signed.zip",
    "SHA256SUMS",
  ], "v2.2.3");
  assert.match(html, /href="Mosael-2\.2\.3-arm64\.dmg"/);
  assert.match(html, /href="Mosael%20Setup%202\.2\.3\.exe"/);
  assert.match(html, /href="SHA256SUMS"/);
  assert.doesNotMatch(html, /mac-signed\.zip"/);
  assert.doesNotMatch(html, /browser-extension\.zip"/);
});

test("R2 下载页转义版本文本并链接浏览器扩展", () => {
  const html = renderDownloadPage(["mosael-browser-extension.zip"], "v2.2.3-beta<1");
  assert.match(html, /2\.2\.3-beta&lt;1/);
  assert.doesNotMatch(html, /beta<1/);
  assert.match(html, /href="mosael-browser-extension\.zip"/);
});
