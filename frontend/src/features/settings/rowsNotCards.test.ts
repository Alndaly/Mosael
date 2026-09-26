/**
 * 设置页里的一项是**一行**,不是一张带边框的卡片。
 *
 * 起因是用户的原话:「设置页面中有一些这样的列表 UI 和整体系统格格不入」。转写、配音、人声分离、
 * 降噪四页各自把每个引擎画成 `rounded-lg border bg-background px-3 py-2.5` 的卡片,一叠叠在
 * 分组里 —— 而分组本来就用分隔线把一行行隔开(SettingsGroup 的 `[&>*+*]:border-t`),其余设置
 * 全是这个样子。卡片套在分组里,等于在一个画了线的列表里又给每一行加一个框。
 *
 * 现在这类列表一律走 `SettingsItemRow`(components/settings/settings-layout.tsx):名字 + 元信息
 * + 说明在左,状态或按钮在右,进度横贯在底下。这条棘轮拦的是下一处再手搓卡片:
 * `features/settings` 与 `components/settings` 里同时带**圆角 + 整圈边框 + 表面底色**的类串。
 *
 * 存量冻结在 GRANDFATHERED,每一条写清为什么它就该是一个框;清单只减不增。
 */

// 这条测试是一道**棘轮**:它进 docs/CONVENTIONS.md 的清单,由 scripts/sync-ratchet-docs.py 生成。
export const RATCHET = true;

import { readFileSync, readdirSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

const SRC = join(import.meta.dirname, "..", "..");
const ROOTS = [join(SRC, "features", "settings"), join(SRC, "components", "settings")];

/** 键是 `文件: 类串`(不带行号 —— 挪一行代码就要改清单的话,清单就没人愿意维护了)。 */
const GRANDFATHERED = new Map<string, string>([
  [
    "features/settings/PricingRuleBrowser.tsx: grid min-w-0 content-start gap-3 rounded-lg border border-border bg-panel p-4",
    "成本规则的**卡片视图**是用户要的,右上角能切成列表;它是网格里的一格,不是分组里的一行",
  ],
  [
    "features/settings/ModelSettingsDialog.tsx: grid grid-cols-[minmax(0,1fr)_auto] items-center gap-3 rounded-md border border-border bg-panel px-3 py-2.5",
    "在弹窗里,没有 SettingsGroup 的分隔线可借;每个开关自带底色是那个弹窗的分组方式",
  ],
  ["features/settings/ProviderOAuthDialog.tsx: grid gap-1.5 rounded-md border border-border bg-panel p-2.5", "弹窗里的说明框"],
  [
    "features/settings/ProviderProfilesSection.tsx: m-0 rounded-md border border-border bg-panel p-2 text-ui-xs leading-[1.5] text-muted-foreground",
    "表单里的一段提示,不是列表里的一项",
  ],
  [
    "features/settings/FeishuSection.tsx: block rounded-lg border border-border bg-background p-2.5 text-center text-[22px] font-semibold tracking-[0.22em] tabular-nums",
    "绑定弹窗里那串绑定码,要一眼框出来抄",
  ],
  [
    "features/settings/GenerationProfileForm.tsx: flex min-h-10 flex-wrap items-center gap-1 rounded-md border border-field-border bg-panel px-2 py-1.5",
    "这是一个输入框(可增删的标签),描边是字段的描边",
  ],
]);

function sourceFiles(dir: string): string[] {
  return readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
    const full = join(dir, entry.name);
    if (entry.isDirectory()) return sourceFiles(full);
    return entry.name.endsWith(".tsx") && !entry.name.includes(".test.") ? [full] : [];
  });
}

const ROUNDED = /(?:^|\s)rounded(?:-(?:sm|md|lg|xl|2xl))?(?=\s|$)/;
/** 整圈边框:`border` 本身。`border-t`、`border-0`、`border-border`(只是颜色)都不算。 */
const FULL_BORDER = /(?:^|\s)border(?=\s|$)/;
const SURFACE = /(?:^|\s)bg-(?:background|panel|card)(?=\s|$)/;

function cardClasses(): string[] {
  const found: string[] = [];
  for (const file of ROOTS.flatMap(sourceFiles)) {
    const source = readFileSync(file, "utf8");
    for (const [, literal] of source.matchAll(/"([^"\n]*)"/g)) {
      if (ROUNDED.test(literal) && FULL_BORDER.test(literal) && SURFACE.test(literal)) {
        found.push(`${file.slice(SRC.length + 1)}: ${literal}`);
      }
    }
  }
  return [...new Set(found)];
}

describe("设置里的列表是行,不是卡片", () => {
  it("不新增带圆角 + 整圈边框 + 表面底色的容器", () => {
    expect(cardClasses().filter((key) => !GRANDFATHERED.has(key))).toEqual([]);
  });

  it("清单只减不增:修好的那条要从清单里删掉", () => {
    const current = new Set(cardClasses());
    expect([...GRANDFATHERED.keys()].filter((key) => !current.has(key))).toEqual([]);
  });

  it("认得出此前那种引擎卡片", () => {
    const old = "grid gap-2 rounded-lg border border-border bg-background px-3 py-2.5";
    expect(ROUNDED.test(old) && FULL_BORDER.test(old) && SURFACE.test(old)).toBe(true);
  });
});
