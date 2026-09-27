/**
 * 审核界面里清单的逐行差异(ADR 0026 §4「审核界面并排显示」)。权限、工具、文件的增删改由社区服务
 * 算好给出;清单它只给顶层键的变化,官网把上一版拼回来再按缩进 JSON 逐行比(最长公共子序列)。
 * 清单几十到几百行,O(n·m) 的表足够;超过上限就不逐行对齐了,整份标成替换 —— 审核的人看到
 * 「全变了」,比页面卡住好。
 */

export type DiffLine = { kind: "same" | "added" | "removed"; text: string };

const MAX_CELLS = 400_000;

export function diffLines(before: string, after: string): DiffLine[] {
  const a = before ? before.split("\n") : [];
  const b = after ? after.split("\n") : [];
  if (a.length * b.length > MAX_CELLS) {
    return [...a.map((text) => ({ kind: "removed" as const, text })), ...b.map((text) => ({ kind: "added" as const, text }))];
  }
  // lcs[i][j] = a[i..] 与 b[j..] 的最长公共子序列长度。
  const lcs: number[][] = Array.from({ length: a.length + 1 }, () => Array.from({ length: b.length + 1 }, () => 0));
  for (let i = a.length - 1; i >= 0; i -= 1) {
    for (let j = b.length - 1; j >= 0; j -= 1) {
      lcs[i][j] = a[i] === b[j] ? lcs[i + 1][j + 1] + 1 : Math.max(lcs[i + 1][j], lcs[i][j + 1]);
    }
  }
  const out: DiffLine[] = [];
  let i = 0;
  let j = 0;
  while (i < a.length && j < b.length) {
    if (a[i] === b[j]) {
      out.push({ kind: "same", text: a[i] });
      i += 1;
      j += 1;
    } else if (lcs[i + 1][j] >= lcs[i][j + 1]) {
      out.push({ kind: "removed", text: a[i] });
      i += 1;
    } else {
      out.push({ kind: "added", text: b[j] });
      j += 1;
    }
  }
  while (i < a.length) out.push({ kind: "removed", text: a[i++] });
  while (j < b.length) out.push({ kind: "added", text: b[j++] });
  return out;
}

/** 键排好序的缩进 JSON:两版清单里键的顺序不同,不该算差异。 */
export function stableJson(value: unknown): string {
  const sort = (input: unknown): unknown => {
    if (Array.isArray(input)) return input.map(sort);
    if (input && typeof input === "object") {
      return Object.fromEntries(
        Object.keys(input as Record<string, unknown>)
          .sort()
          .map((key) => [key, sort((input as Record<string, unknown>)[key])]),
      );
    }
    return input;
  };
  return JSON.stringify(sort(value), null, 2);
}
