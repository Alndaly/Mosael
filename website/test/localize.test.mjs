import assert from "node:assert/strict";
import test from "node:test";

import "./support/alias.mjs";

const { localizeTree } = await import("../src/lib/community/localize.ts");

// 官方条目(从静态索引迁进社区服务的那一批)的标题、简介、准备项、步骤是 {zh, en};页面此前直接渲染它,
// 整页崩在「Objects are not valid as a React child (found: object with keys {zh, en})」。
const official = {
  items: [
    {
      slug: "full-video-generation",
      title: { zh: "从主题到完整视频", en: "Topic to finished video" },
      summary: { zh: "输入一个主题……", en: "Turn a topic…" },
      tags: ["video"],
      extra: { requires: { zh: ["AI 对话模型"], en: ["Chat model"] }, stages: { zh: ["写脚本"], en: ["Script"] } },
      downloads: 3,
    },
    { slug: "mine", title: "用户提交的是字符串", summary: "", tags: [] },
  ],
  next_cursor: null,
};

test("双语字段换成这一页的语言,别的原样", () => {
  const zh = localizeTree(official, "zh");
  assert.equal(zh.items[0].title, "从主题到完整视频");
  assert.deepEqual(zh.items[0].extra.requires, ["AI 对话模型"]);
  assert.deepEqual(zh.items[0].tags, ["video"]);
  assert.equal(zh.items[0].downloads, 3);
  assert.equal(zh.items[1].title, "用户提交的是字符串");
  assert.equal(zh.next_cursor, null);
});

test("认 BCP 47 前缀;缺这种语言时用另一种", () => {
  assert.equal(localizeTree(official, "en-US").items[0].title, "Topic to finished video");
  assert.equal(localizeTree(official, "zh-CN").items[0].summary, "输入一个主题……");
  assert.equal(localizeTree({ title: { zh: "只有中文" } }, "en").title, "只有中文");
});

test("不是只有 zh / en 的对象不动", () => {
  const value = { media: { zh: "x", url: "/a.png" }, empty: {} };
  assert.deepEqual(localizeTree(value, "en"), value);
});
