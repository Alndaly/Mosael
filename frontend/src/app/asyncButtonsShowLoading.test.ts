/**
 * 按下去要等一阵的按钮,必须看得出「正在做」。
 *
 * 真机:批量删除项目,点了确认之后弹窗一动不动 —— 用户只能猜是不是没点上,再点一次就是再删一次。
 * 这类按钮的共同形状是 `onClick` 里直接调一个 mutation;它们都要把那个 mutation 的进行中状态交给
 * `loading`(Button 会转圈并禁用)。确认弹窗那一种由 ConfirmDialog 的必填 `pending` 钉住,这里钉
 * 普通按钮。
 */
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join } from "node:path";
import { expect, it } from "vitest";

function sources(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const path = join(dir, name);
    if (statSync(path).isDirectory()) return sources(path);
    return name.endsWith(".tsx") && !name.includes(".test.") ? [path] : [];
  });
}

//: 一个 <Button …> 开标签(属性里允许一层嵌套的花括号)。
const BUTTON = /<Button\b(?:[^>{]|\{(?:[^{}]|\{[^{}]*\})*\})*>/g;

it("onClick 里直接调 mutation 的按钮都带 loading", () => {
  const missing: string[] = [];
  for (const file of sources(join(__dirname, ".."))) {
    const text = readFileSync(file, "utf8");
    for (const match of text.matchAll(BUTTON)) {
      const tag = match[0];
      if (/onClick=\{[\s\S]*?\.mutate(Async)?\(/.test(tag) && !tag.includes("loading=")) {
        const line = text.slice(0, match.index).split("\n").length;
        missing.push(`${file.replace(/^.*\/src\//, "src/")}:${line}`);
      }
    }
  }
  expect(missing, `这些按钮按下去要等,却没有 loading:\n${missing.join("\n")}`).toEqual([]);
});
