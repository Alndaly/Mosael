/**
 * 设置组件自己拥有纵向节奏，调用方不能再从外面叠加一层。
 *
 * SettingsGroup/Row/Block/ListBlock/ListItem/Field/Form 分别已经定义 header、row、block 与字段间距。
 * 外部若再传 mt/mb/my/pt/pb/py，或把自带 py 的 SettingsList 塞进自带 py+gap 的 SettingsRow，
 * 视觉间距会随组合方式翻倍。
 */

// 这条测试是一道棘轮:它进 docs/CONVENTIONS.md 的清单,由 scripts/sync-ratchet-docs.py 生成。
export const RATCHET = true;

import { readFileSync, readdirSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

const SRC = join(import.meta.dirname, "..");

function sourceFiles(dir: string): string[] {
  return readdirSync(dir, { withFileTypes: true }).flatMap((entry) => {
    const full = join(dir, entry.name);
    if (entry.isDirectory()) return sourceFiles(full);
    return entry.name.endsWith(".tsx") && !entry.name.includes(".test.") ? [full] : [];
  });
}

const VERTICAL_SPACE = /(?:^|\s)(?:mt|mb|my|pt|pb|py)-[^\s"']+/;

describe("settings spacing ownership", () => {
  it("consumers do not add vertical spacing to primitives that already own it", () => {
    const offenders: string[] = [];

    for (const file of sourceFiles(SRC)) {
      const source = readFileSync(file, "utf8");
      for (const match of source.matchAll(/<Settings(?:Group|Row|Block|ListBlock|ListItem|Field|Form)\b[\s\S]*?>/g)) {
        const props = match[0];
        for (const classMatch of props.matchAll(/(?:className|contentClassName)="([^"]*)"/g)) {
          if (VERTICAL_SPACE.test(classMatch[1])) {
            offenders.push(`${file.slice(SRC.length + 1)} → ${classMatch[1]}`);
          }
        }
      }

      for (const match of source.matchAll(/<SettingsBlock\b[^>]*>\s*<[^>]*className="([^"]*)"/g)) {
        if (VERTICAL_SPACE.test(match[1])) {
          offenders.push(`${file.slice(SRC.length + 1)} → SettingsBlock child: ${match[1]}`);
        }
      }

      for (const match of source.matchAll(/<SettingsRow\b[\s\S]*?<\/SettingsRow>/g)) {
        if (match[0].includes("<SettingsList")) {
          offenders.push(`${file.slice(SRC.length + 1)} → SettingsList nested in SettingsRow`);
        }
      }

      for (const match of source.matchAll(/<SettingsBlock\b[\s\S]*?<\/SettingsBlock>/g)) {
        if (match[0].includes("<SettingsList") && !match[0].includes("<SettingsBlockTitle")) {
          offenders.push(`${file.slice(SRC.length + 1)} → untitled SettingsList nested in SettingsBlock`);
        }
      }
    }

    expect(offenders).toEqual([]);
  });
});
