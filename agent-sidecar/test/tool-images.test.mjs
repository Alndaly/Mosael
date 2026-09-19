/** 工具截图:轮内只留最近几张,轮末全部换成说明,看不了图的模型一张不发。 */
import assert from "node:assert/strict";
import { mkdirSync } from "node:fs";
import path from "node:path";
import test from "node:test";
import { pathToFileURL } from "node:url";

import { build } from "esbuild";

const outdir = path.join(import.meta.dirname, "..", "dist");
mkdirSync(outdir, { recursive: true });
const outfile = path.join(outdir, "tool-images.test.mjs");
await build({
  entryPoints: [path.join(import.meta.dirname, "..", "src", "toolImages.ts")],
  outfile, format: "esm", bundle: true, platform: "node", packages: "external",
});
const { RECENT_TOOL_IMAGES, dropToolImages, keepRecentToolImages } = await import(pathToFileURL(outfile).href);

const image = (n) => ({ type: "image", data: `img${n}`, mimeType: "image/jpeg" });
const look = (n) => ({ role: "toolResult", toolCallId: `c${n}`, toolName: "view_scene", content: [{ type: "text", text: "{}" }, image(n)] });
const user = { role: "user", content: [{ type: "text", text: "看看" }, image("user")] };
const images = (messages) => messages.flatMap((m) => (Array.isArray(m.content) ? m.content : [])).filter((b) => b.type === "image").map((b) => b.data);

test("轮内只留最近几张工具截图,用户自己贴的图不动", () => {
  const messages = [user, ...Array.from({ length: 7 }, (_, i) => look(i))];
  const kept = keepRecentToolImages(messages, true);
  assert.deepEqual(images(kept), ["imguser", ...Array.from({ length: RECENT_TOOL_IMAGES }, (_, i) => `img${7 - RECENT_TOOL_IMAGES + i}`)]);
  assert.ok(kept[1].content.some((b) => b.type === "text" && b.text.includes("已省略")));
});

test("没有要省的就原样返回", () => {
  const messages = [user, look(0)];
  assert.equal(keepRecentToolImages(messages, true), messages);
});

test("看不了图的模型一张工具截图都不发", () => {
  assert.deepEqual(images(keepRecentToolImages([user, look(0)], false)), ["imguser"]);
});

test("轮末存会话状态前,工具截图全部换成说明", () => {
  const stored = dropToolImages([user, look(0), look(1)]);
  assert.deepEqual(images(stored), ["imguser"]);
  assert.ok(stored[2].content.some((b) => b.type === "text" && b.text.includes("上一轮")));
});
