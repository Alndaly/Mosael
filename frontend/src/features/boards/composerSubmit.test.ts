/**
 * 画板上四张表单的提交键**必须走同一份 useSubmitting**。
 *
 * 各写各的话,两头都会漏,而漏了都不报错:
 *
 *  · 只在开头 setTrue → 失败后那个圈永远转下去(用户既不知道失败了,也再点不动第二次);
 *  · 干脆不置 → 点下去几百毫秒内毫无变化,用户以为没点上,再点一次,于是发两遍。
 *
 * 这两种此前**同时存在**于这四个文件里。所以钉住来源,而不是钉住"某个文件里有个 spinner"。
 */
import fs from "node:fs";
import path from "node:path";

import { describe, expect, it } from "vitest";

const HERE = __dirname;
const COMPOSERS = ["NodeComposer.tsx", "NoteComposer.tsx", "AudioComposer.tsx", "TrimComposer.tsx"];

describe("画板表单的提交状态", () => {
  it.each(COMPOSERS)("%s 走共用的 useSubmitting", (file) => {
    const source = fs.readFileSync(path.join(HERE, file), "utf8");
    expect(source, `${file}:没有引入 useSubmitting`).toContain("useSubmitting");
    expect(source, `${file}:提交没有交给 run()`).toMatch(/\brun\(\(\) =>/);
  });

  it.each(COMPOSERS)("%s 不再自己维护一份 sending", (file) => {
    const source = fs.readFileSync(path.join(HERE, file), "utf8");
    // 自己维护的那份正是「失败后停不下来」的来源 —— 它只在开头置 true。
    expect(source, `${file}:又出现了本地的 sending 状态`).not.toMatch(/setSending\s*\(/);
  });
});
