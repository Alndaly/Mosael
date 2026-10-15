/**
 * 在跑的时候点不了的按钮,要让人看得出它在跑:转圈 + `aria-busy`,不能只是变灰。
 *
 * 只变灰的按钮在用户眼里是「点了没反应」:看不出是没点上、点不了,还是正在做。维护者在模型库的详情里点
 * 「在 Civitai 上找」,按钮只是灰了 —— 那一趟要那台机器把整个文件读一遍,好一阵什么都看不出来。
 * app/buttonPending.test.ts 管的是「点下去发请求的按钮接上 loading」;这一条管反过来那一半:`disabled`
 * 里等着一件在跑的事,却不转圈。
 *
 * 认法:`Button` / `IconButton` / 原生 `<button>` 的 `disabled={…}` 里出现一个「在跑」样的名字 ——
 * `isPending`、`pending`、`busy`、`saving`、`running`、`loading`、`submitting`,含拼在驼峰里的
 * (`save.isPending`、`bulkBusy`、`poemLoading`、`pendingId`)—— 这颗按钮就得有 `loading`(原生按钮:
 * 子内容里有转圈,`<Loader2>` 或 `animate-…spin`)。
 *
 * 真例外是「别的事在跑,所以这颗点不了」:转圈的是在跑的那一处(旁边的确认键、状态条、任务中心),
 * 这颗再转一个就成了两处都在跑。两类:
 * - 取消键(子内容就是 `{t("cancel")}`):确认键在跑时它按不动、弹窗也关不掉(见 ConfirmDialog 的说明),
 *   转圈的是旁边那颗确认键。这一类按写法认,不逐个列。
 * - 别的逐个写进 EXCEPTIONS,每条写清楚在跑的是谁、进度在哪看。
 */
// 这条测试是一道**棘轮**:它进 docs/CONVENTIONS.md 的清单,由 scripts/sync-ratchet-docs.py 生成。
export const RATCHET = true;
import { describe, expect, it } from "vitest";

import { childrenOf, openTags, readSource, tsxSources, type OpenTag } from "./jsxSource";

/** 共用组件自己实现这条(Button 的 `disabled || loading` 就是它),不在检查范围里。 */
const OWNERS = ["components/ui/"];

/** 存量:只减不增。`文件` → 还剩几处。 */
const STOCK: Record<string, number> = {};

/**
 * 真例外:`文件` → 那几颗按钮的 `disabled` 表达式(源码原样、去掉空白)和为什么不转圈。一条只放过 `count` 颗
 * (不写就是一颗):同一个文件里再多一颗同样写法的,照样拦下来想一遍;表达式改了也得回来重新想。
 */
const EXCEPTIONS: Record<string, { disabled: string; count?: number; why: string }[]> = {
  "features/browser-pool/session-tools/BrowserSessionTools.tsx": [
    { disabled: "busy", why: "一组工具里的选项:点了就收起,在跑的那一样由下面的状态条转圈、说做到哪了;这期间选项点不了" },
  ],
  "features/editor/TranscriptPanel.tsx": [
    { disabled: "noAsrEngine||transcriptsLoading||allTranscribed",
      why: "transcriptsLoading 是逐字稿清单还没读回来(还不知道哪些转过了),不是转写在跑;转圈会被读成「正在转写」" },
  ],
  "features/notes/NoteList.tsx": [
    { disabled: "busy", count: 2,
      why: "列表行、「取消选择」:一样批量操作在跑时整列锁住;转圈的是点的那一颗" },
    { disabled: "busy||Boolean(writeBlocked)",
      why: "「彻底删除」只是打开确认框,删除在确认框里转;批量操作在跑时、只读成员(D62)都点不了" },
  ],
  "features/notes/SaveToNote.tsx": [
    { disabled: "busy", why: "存哪一种形状的分段选项:存的时候不让换,转圈的是「新建」或追加的那一行" },
  ],
  "features/plugins/WorkflowImport.tsx": [
    { disabled: "busy", why: "「再导入一个」和取消一样是退回去:存的时候按不动,转圈的是旁边那颗确认键" },
  ],
  "features/scenes/SceneBlender.tsx": [
    { disabled: "busy", why: "「刷新」:面板里的一样操作或场景那边的导出在跑,转圈的是那一颗,面板底下也有一行在跑的状态" },
    { disabled: "busy||pending", why: "「打开收到的场景」只是跳页,不跑;有事在跑或场景还没存好时先别跳" },
  ],
  "features/scenes/SceneList.tsx": [
    { disabled: "busy||!chosen.length||Boolean(writeBlocked)",
      why: "「删除所选」只是打开确认框;删除、改名在跑时、只读成员(D62)都点不了,转圈的是确认框、改名框里那颗" },
    { disabled: "busy", count: 2, why: "「取消选择」和卡片本身:删除、改名在跑时整列锁住,转圈的是确认框、改名框里那颗" },
  ],
  "features/scenes/SceneStudio.tsx": [
    { disabled: "!!busy", count: 4,
      why: "「生成素材」入口、播放、物体的显隐和删除:导出、录制、准备生成在跑时编辑器锁住,视口上那块 scene-busy 转圈并写着在做什么" },
    { disabled: "draft.content.shots.length<=1||!!busy", why: "删镜头:同上,编辑器锁住时点不了,进度在视口上" },
  ],
  "features/settings/ProviderProfilesSection.tsx": [
    { disabled: "bulkBusy", why: "「批量删除」只是打开确认框;批量开关、删除在跑时它点不了,转圈的是点的那一颗或确认框" },
  ],
  "features/workflows/WorkflowRevisionHistory.tsx": [
    { disabled: "current||sameContent||restore.isPending", why: "每个版本的「恢复」只是打开确认框;恢复在跑时都点不了,转圈的是确认框里那颗" },
  ],
};

const BUTTONS = new Set(["Button", "IconButton", "button"]);

/** 「在跑」样的名字:整个标识符,或驼峰里的一段(`isPending`、`bulkBusy`、`pendingId`)。 */
const PENDING_WORD =
  /(?:^|[a-z0-9_])(?:Pending|Busy|Saving|Running|Loading|Submitting)(?=[A-Z0-9_]|$)|^(?:pending|busy|saving|running|loading|submitting)(?=[A-Z0-9_]|$)/;

/** 禁用表达式里提到的「在跑」样的名字(字符串里的不算)。 */
export function pendingNames(expression: string): string[] {
  const code = expression.replace(/"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*'|`(?:\\.|[^`\\])*`/g, '""');
  return [...code.matchAll(/[A-Za-z_$][\w$]*/g)].map((match) => match[0]).filter((name) => PENDING_WORD.test(name));
}

/** 子内容里有没有转圈。 */
export function hasSpinner(children: string): boolean {
  return /<Loader2\b/.test(children) || /animate-[\w-]*spin\b/.test(children);
}

/** 取消键:子内容就是 `{t("cancel")}`。 */
export function isCancel(children: string): boolean {
  return children.trim() === '{t("cancel")}';
}

function offenders(): Map<string, string[]> {
  const found = new Map<string, string[]>();
  const add = (file: string, what: string) => found.set(file, [...(found.get(file) ?? []), what]);
  for (const file of tsxSources()) {
    if (OWNERS.some((owner) => file.startsWith(owner))) continue;
    const code = readSource(file);
    const excused = new Map<string, number>();
    for (const one of EXCEPTIONS[file] ?? []) excused.set(one.disabled, (excused.get(one.disabled) ?? 0) + (one.count ?? 1));
    for (const tag of openTags(code)) {
      const flagged = flag(tag, code);
      if (!flagged) continue;
      const left = excused.get(flagged.expression) ?? 0;
      if (left > 0) {
        excused.set(flagged.expression, left - 1);
        continue;
      }
      add(file, `${tag.line}: <${tag.tag} disabled={${flagged.expression}}> 等着 ${flagged.names.join("、")},却不转圈`);
    }
    for (const [expression, left] of excused) {
      if (left > 0) add(file, `EXCEPTIONS 里 disabled={${expression}} 多放过了 ${left} 颗 —— 改好了就删掉`);
    }
  }
  return found;
}

/** 这颗按钮该转圈却没转:返回禁用表达式和里面「在跑」样的名字。 */
function flag(tag: OpenTag, code: string): { expression: string; names: string[] } | null {
  if (!BUTTONS.has(tag.tag)) return null;
  const disabled = tag.attrs.get("disabled");
  if (!disabled?.startsWith("{")) return null;
  const names = pendingNames(disabled);
  if (names.length === 0 || tag.attrs.has("loading")) return null;
  const children = childrenOf(code, tag) ?? "";
  if (isCancel(children)) return null;
  if (tag.tag === "button" && hasSpinner(children)) return null;
  return { expression: disabled.slice(1, -1).replace(/\s+/g, ""), names };
}

describe("在跑的按钮转圈,不只是变灰", () => {
  const found = offenders();

  it("没有新增的只变灰的按钮", () => {
    const grown = [...found].filter(([file, list]) => list.length > (STOCK[file] ?? 0)).map(([file, list]) => `${file}\n    ${list.join("\n    ")}`);
    expect(grown, "给按钮 loading(原生按钮:换上转圈);真是「别的事在跑」的,写进 EXCEPTIONS 并说清楚在跑的是谁").toEqual([]);
  });

  it("存量清单没有过时的条目 —— 改好了就把它从清单里删掉", () => {
    const stale = Object.entries(STOCK).filter(([file, count]) => (found.get(file)?.length ?? 0) < count).map(([file]) => file);
    expect(stale).toEqual([]);
  });

  it("认法本身:驼峰里的「在跑」也算,字符串里的、只是长得像的不算;取消键、带转圈的原生按钮放过", () => {
    expect(pendingNames("save.isPending")).toEqual(["isPending"]);
    expect(pendingNames("!chosen.length || bulkBusy")).toEqual(["bulkBusy"]);
    expect(pendingNames("pendingId !== null")).toEqual(["pendingId"]);
    expect(pendingNames("form.formState.isSubmitting")).toEqual(["isSubmitting"]);
    expect(pendingNames("!!busy")).toEqual(["busy"]);
    expect(pendingNames('status === "running"')).toEqual([]);
    expect(pendingNames("overloading || unbusy || !ready")).toEqual([]);
    expect(isCancel(' {t("cancel")}\n ')).toBe(true);
    expect(isCancel('{t("cancelSelection")}')).toBe(false);
    expect(hasSpinner('{busy ? <Loader2 size={11} className="animate-mosael-spin" /> : <Trash2 />}')).toBe(true);
    expect(hasSpinner('<RefreshCcw className={loading ? "animate-spin" : undefined} />')).toBe(true);
    expect(hasSpinner("<Trash2 /> {t(\"clear\")}")).toBe(false);
  });
});
