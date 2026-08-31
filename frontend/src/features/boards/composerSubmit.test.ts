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

  it("视频时长不使用带系统 spinner 的原生 number 输入", () => {
    const source = fs.readFileSync(path.join(HERE, "NodeComposer.tsx"), "utf8");
    expect(source).not.toContain('type="number"');
  });

  it("生成面板留足宽度并让底部参数换行而不是逐项省略", () => {
    const source = fs.readFileSync(path.join(HERE, "NodeComposer.tsx"), "utf8");
    expect(source).toContain('w-[480px]');
    expect(source).toContain('flex flex-wrap items-center');
    expect(source).toContain('shrink-0 [&>span]:overflow-visible [&>span]:text-clip');
  });

  it("节点上方操作条使用较大的点击区", () => {
    const source = fs.readFileSync(path.join(HERE, "BoardCanvas.tsx"), "utf8");
    expect(source).toContain('rounded-full border border-border-strong bg-panel p-1.5');
    expect(source).toContain('h-7 w-7 cursor-pointer');
  });
});
