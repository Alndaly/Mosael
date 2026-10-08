/**
 * 挨着一个值、一行说明的次要动作走 Button 的 `variant="inline"`(行内动作),不摆正文字号的按钮。
 *
 * 维护者截图:模型详情「概要」里,「在 Civitai 上找」「标为 NSFW」是 sm 档、正文字号、16px 图标,比旁边的值(「不知道」
 * 「没有依据说它是 NSFW」)还醒目 —— 一行里视觉最重的,反倒是次要动作。行内动作比正文小一档、次要色、悬停才显出底色,
 * 图标跟着缩小,也不撑高那一行(见 components/ui/button.tsx 那一档的说明)。
 *
 * 这条拦两种形状:
 * - **值那一格里的按钮**:`<dd>`,以及几处「名字 | 值」排的行组件(OverviewRow、InfoRow)里面的 `<Button>`,
 *   要么是 `variant="inline"`,要么就不该放在值的旁边;
 * - **手搓的行内按钮**:在 Button 上用 className 把高度压成 `h-6`、或者在 xs 以外的档位上把字号改成 `text-ui-xs` ——
 *   那是在说「我要一颗行内动作」,而这一档已经有了。
 */
// 这条测试是一道**棘轮**:它进 docs/CONVENTIONS.md 的清单,由 scripts/sync-ratchet-docs.py 生成。
export const RATCHET = true;
import { describe, expect, it } from "vitest";

import { childrenOf, classText, openTags, readSource, tsxSources } from "@/design/jsxSource";

/** 「名字 | 值」排的那一格:里面的按钮挨着的是值。 */
const VALUE_CELLS = new Set(["dd", "OverviewRow", "InfoRow"]);

/**
 * 还没改的。只许减少。
 * 定时任务那一页正在另一路做 ADR 0047 / 0054(管理页、邀请),这一批先不动,等它合完再改成行内动作。
 */
const KNOWN = new Set(["features/scheduler/SchedulerView.tsx"]);

const unquote = (value: string | undefined) => (value ?? "").replace(/^\{?["'`]?|["'`]?\}?$/g, "");

function offenders() {
  const inCells: string[] = [];
  const handRolled: string[] = [];
  for (const rel of tsxSources()) {
    const code = readSource(rel);
    const tags = openTags(code);
    for (const cell of tags.filter((tag) => VALUE_CELLS.has(tag.tag) && !tag.selfClosing)) {
      const inner = childrenOf(code, cell);
      if (!inner) continue;
      for (const button of openTags(inner).filter((tag) => tag.tag === "Button")) {
        if (unquote(button.attrs.get("variant")) !== "inline" && !KNOWN.has(rel)) inCells.push(`${rel}:${cell.line}(<${cell.tag}> 里的 <Button>)`);
      }
    }
    for (const button of tags.filter((tag) => tag.tag === "Button")) {
      if (unquote(button.attrs.get("variant")) === "inline") continue;
      const classes = classText(button.attrs.get("className")).split(/\s+/);
      const size = unquote(button.attrs.get("size"));
      if (classes.includes("h-6") || (classes.includes("text-ui-xs") && size !== "xs")) {
        handRolled.push(`${rel}:${button.line}`);
      }
    }
  }
  return { inCells, handRolled };
}

describe("行内动作", () => {
  const found = offenders();

  it("值那一格里的按钮用 variant=\"inline\"", () => {
    expect(found.inCells, "挨着值的动作改用 <Button variant=\"inline\">;它要是主动作,就别放在值的旁边").toEqual([]);
  });

  it("没有在 Button 的 className 里手搓行内动作", () => {
    expect(found.handRolled, "h-6 / 非 xs 档上的 text-ui-xs:改用 variant=\"inline\"(行内动作)或 size=\"xs\"(工具栏那一档)").toEqual([]);
  });

  it("清单里的还没改 —— 改好了就从 KNOWN 里删掉", () => {
    for (const rel of KNOWN) {
      const code = readSource(rel);
      const stillThere = openTags(code)
        .filter((tag) => VALUE_CELLS.has(tag.tag) && !tag.selfClosing)
        .some((cell) => openTags(childrenOf(code, cell) ?? "").some((tag) => tag.tag === "Button" && unquote(tag.attrs.get("variant")) !== "inline"));
      expect(stillThere, `${rel} 已经改好了`).toBe(true);
    }
  });

  it("扫得到东西 —— 别变成空转", () => {
    const code = readSource("features/plugins/ModelDetail.tsx");
    const cells = openTags(code).filter((tag) => tag.tag === "OverviewRow" && !tag.selfClosing);
    expect(cells.length, "模型详情的概要里应当有几行 OverviewRow").toBeGreaterThan(2);
    expect(code).toMatch(/variant="inline"/);
  });
});
