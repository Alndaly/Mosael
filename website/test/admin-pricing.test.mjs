import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import test from "node:test";

const ROOT = path.resolve(import.meta.dirname, "..");
const read = (relative) => fs.readFileSync(path.join(ROOT, relative), "utf8");
const consoleSource = read("src/components/admin/admin-console.tsx");
const messages = read("src/i18n/messages.ts");

/**
 * 套餐表单里的 `price_cents` 是**分**，用户输入 1990；
 * 套餐列表把同一数值格式化成人看的 `¥19.90`。两处单位不同，表头也必须跟着不同：
 * 列表写「价格」/「Price」，表单才写「价格（分）」/「Price (cents)」。
 */
test("套餐列表显示元，表单仍按分输入", () => {
  assert.match(consoleSource, /cents \/ 100/, "列表价格没有把分换算成元");
  assert.match(consoleSource, /<TableHead>\{copy\.price\}<\/TableHead>/, "套餐列表表头仍在说「分」");
  assert.match(consoleSource, /<Field label=\{copy\.priceCents\}>/, "表单没有标明输入单位是分");
  assert.match(messages, /price: "价格"/, "中文缺少列表价格文案");
  assert.match(messages, /priceCents: "价格（分）"/, "中文表单价格文案错了");
  assert.match(messages, /price: "Price"/, "英文缺少列表价格文案");
  assert.match(messages, /priceCents: "Price \(cents\)"/, "英文表单价格文案错了");
});
