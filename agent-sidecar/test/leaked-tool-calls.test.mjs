/** 写成正文标记的工具调用:按一小段一小段到达时,标记一个字都不往外推;普通回答原样转发(见 src/leakedToolCalls.ts)。 */
import assert from "node:assert/strict";
import { mkdirSync } from "node:fs";
import path from "node:path";
import test from "node:test";
import { pathToFileURL } from "node:url";

import { build } from "esbuild";

const outdir = path.join(import.meta.dirname, "..", "dist");
mkdirSync(outdir, { recursive: true });
const outfile = path.join(outdir, "leaked-tool-calls.test.mjs");
await build({
  entryPoints: [path.join(import.meta.dirname, "..", "src", "leakedToolCalls.ts")],
  outfile, format: "esm", bundle: true, platform: "node", packages: "external",
});
const { leakedToolCalls, hidingLeakedToolCalls } = await import(pathToFileURL(outfile).href);
const { createAssistantMessageEventStream } = await import("@earendil-works/pi-ai");

const B = "｜｜";
const LEAKED = `5 张首帧全部出好了。先摸清时间线的操作清单。\n\n<${B}DSML${B} calls>\n`
  + `<${B}DSML${B} invoke name="edit_timeline">\n`
  + `<${B}DSML${B} parameter name="sequence_id" string="true">seq-1</${B}DSML${B} parameter>\n`
  + `</${B}DSML${B} invoke>\n<${B}DSML${B} invoke name="plugin_tools">\n`
  + `<${B}DSML${B} parameter name="query" string="true">comfyui krea2</${B}DSML${B} parameter>\n`
  + `</${B}DSML${B} invoke>\n</${B}DSML${B} calls>`;

test("认出标记之前那句话和它想调的工具;没有标记是 null", () => {
  assert.deepEqual(leakedToolCalls(LEAKED), { before: "5 张首帧全部出好了。先摸清时间线的操作清单。", tools: ["edit_timeline", "plugin_tools"] });
  assert.equal(leakedToolCalls("普通的一句回答,里面有个 < 号"), null);
});

async function run(text, chunk) {
  const source = createAssistantMessageEventStream();
  const wrapped = hidingLeakedToolCalls(source);
  const message = { role: "assistant", content: [{ type: "text", text: "" }], stopReason: "stop" };
  source.push({ type: "start", partial: message });
  source.push({ type: "text_start", contentIndex: 0, partial: message });
  for (let i = 0; i < text.length; i += chunk) {
    message.content[0].text = text.slice(0, i + chunk);
    source.push({ type: "text_delta", contentIndex: 0, delta: text.slice(i, i + chunk), partial: message });
  }
  source.push({ type: "text_end", contentIndex: 0, content: text, partial: message });
  source.push({ type: "done", reason: "stop", message: { ...message, content: [{ type: "text", text }] } });
  source.end();
  let shown = "";
  for await (const event of wrapped) if (event.type === "text_delta") shown += event.delta;
  return { shown, result: await wrapped.result() };
}

test("不管怎么切块,标记都不往外推;结束的消息里标记去掉、记下想调的工具,不造工具调用", async () => {
  for (const chunk of [1, 3, 7, 50]) {
    const { shown, result } = await run(LEAKED, chunk);
    assert.equal(shown, "5 张首帧全部出好了。先摸清时间线的操作清单。", `chunk=${chunk}`);
    assert.deepEqual(result.content, [{ type: "text", text: "5 张首帧全部出好了。先摸清时间线的操作清单。" }]);
    assert.deepEqual(result.mosaelLeakedToolCalls, ["edit_timeline", "plugin_tools"]);
    assert.equal(result.stopReason, "stop");
  }
});

test("普通回答原样转发,结尾压着的「<」和空白在块结束时补推出去", async () => {
  const text = "比较一下:a < \n";
  const { shown, result } = await run(text, 1);
  assert.equal(shown, text);
  assert.equal(result.mosaelLeakedToolCalls, undefined);
});

test("没写全的开头(实测:两行 `<｜｜DSML｜｜ calls`,没有 `>`)也认得出来,标记之前那句话留下", async () => {
  const broken = `我先并行做两件事:重出第 3 镜,同时读取时间线现状。\n\n<${B}DSML${B} calls\n\n<${B}DSML${B} calls`;
  assert.deepEqual(leakedToolCalls(broken), { before: "我先并行做两件事:重出第 3 镜,同时读取时间线现状。", tools: [] });
  const { shown, result } = await run(broken, 3);
  assert.equal(shown, "我先并行做两件事:重出第 3 镜,同时读取时间线现状。");
  assert.deepEqual(result.mosaelLeakedToolCalls, []);
});
