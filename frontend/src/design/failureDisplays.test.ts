/**
 * 失败展示走 `FailureCard`(components/failure):一次失败(任务、工具调用、工作流的一步、画板格子、发布、下载、安装……)给人看的
 * 样子全应用只此一份 —— 卡头状态、一句「出了什么事」、「原因 / 怎么修」、动作行、原文收进详情;放不下一张卡的地方用紧凑档或一行档。
 *
 * 维护者:「智能体和无限画布、工作流等存在类似情况的失败的那个卡片 UI 也进行彻底的重构排版」。此前各处各写一份 —— 一行红字、
 * 一块粉红、原文头三行、一个灯泡加一大段话 —— 新写的失败展示照着手边那份抄,于是又多一种。
 *
 * 认法:功能代码里,一个原生标签的 className 带着失败色(`text-destructive`,或者用 destructive 调出来的底色、边框),而它的内容里
 * 摆的是一句失败原因(`{…error…}`、`{…reason…}`、`{…failure…}`、`t("…Failed")`、`t("…Error")`)—— 那就是手写的失败展示。
 * 表单校验的提示用 components/ui/form 的 FormMessage;只是给一个词上色(「失败」两个字的状态胶囊)不算 —— 内容里没有原因。
 *
 * 存量按文件冻结(只减不增)。改用 FailureCard 之后把那个文件的数字改小 —— 表才不会变成谁都能往里加的白名单。
 */
// 这条测试是一道**棘轮**:它进 docs/CONVENTIONS.md 的清单,由 scripts/sync-ratchet-docs.py 生成。
export const RATCHET = true;
import { describe, expect, it } from "vitest";

import { childrenOf, classText, openTags, readSource, tsxSources } from "./jsxSource";

const OWNERS = ["components/failure/", "components/ui/"];

/** 存量:只减不增。`文件` → 还剩几处。 */
const STOCK: Record<string, number> = {
  "components/app/ConfigNotice.tsx": 1,
  "components/app/FailureDetails.tsx": 2,
  "components/app/MediaPreviewPlayer.tsx": 1,
  "components/app/ServerPicker.tsx": 1,
  "components/generation/LocalNsfw.tsx": 2,
  "features/admin/ProviderPricingSection.tsx": 1,
  "features/agent/skills/SkillCardPreviews.tsx": 1,
  "features/ai-studio/ChatWorkspace.tsx": 1,
  "features/auth/LoginView.tsx": 1,
  "features/boards/assetUpload.tsx": 1,
  "features/browser-pool/session-tools/BrowserSessionTools.tsx": 1,
  "features/browser-pool/session-tools/VideoPanel.tsx": 1,
  "features/editor/TranscriptPanel.tsx": 2,
  "features/editor/playback/PreviewUnavailable.tsx": 1,
  "features/entities/DrawDialog.tsx": 1,
  "features/entities/SpeakDialog.tsx": 1,
  "features/markers/ShortcutRecorder.tsx": 1,
  "features/plugins/CodeConfigField.tsx": 2,
  "features/plugins/ConnectionLocalService.tsx": 3,
  "features/plugins/LocalServiceVersion.tsx": 1,
  "features/plugins/ModelDetail.tsx": 1,
  "features/plugins/ModelLibrary.tsx": 2,
  "features/plugins/WorkflowAppEditor.tsx": 1,
  "features/plugins/WorkflowFolders.tsx": 3,
  "features/plugins/WorkflowFormsUpgrade.tsx": 2,
  "features/plugins/WorkflowImport.tsx": 1,
  "features/plugins/WorkflowNodeInstall.tsx": 1,
  "features/plugins/WorkflowPathField.tsx": 1,
  "features/plugins/appForm/FormsBar.tsx": 1,
  "features/plugins/workbench/OpenInWorkbench.tsx": 1,
  "features/plugins/workbench/workbenchParts.tsx": 1,
  "features/publish/PublishView.tsx": 1,
  "features/scheduler/SchedulerView.tsx": 2,
  "features/settings/AccountSection.tsx": 1,
  "features/settings/FeishuSection.tsx": 2,
  "features/settings/ModelSettingsDialog.tsx": 1,
  "features/settings/ProviderOAuthDialog.tsx": 1,
  "features/settings/ProviderProfilesSection.tsx": 1,
  "features/settings/ProviderQuota.tsx": 2,
  "features/workflows/WorkflowNode.tsx": 1,
  "features/workflows/WorkflowRevisionHistory.tsx": 1,
  "features/workflows/WorkflowRunHistory.tsx": 1,
};

/** 失败色:红字,或者拿 destructive 调出来的底色 / 边框(`bg-destructive/10`、`border-destructive/40`、`color-mix(…var(--destructive)…)`)。 */
const FAILURE_TONE = /(?:^|\s)(?:[\w-]+:)*(?:text-destructive|bg-destructive\S*|border-destructive\S*|\S*var\(--destructive\)\S*)(?=\s|$)/;
/** 内容里是一句失败原因:一个带 error / reason / failure / failed 的表达式,或一条「…失败」「…错误」的文案。 */
const FAILURE_TEXT = /\{[^{}]*\b(?:\w*[eE]rror\w*|reason|failure|failed|why)\b[^{}]*\}|\bt\(\s*["'`][\w]*(?:Failed|Error)\w*["'`]/;

export function handRolledFailures(code: string): string[] {
  const found: string[] = [];
  for (const tag of openTags(code)) {
    if (!/^[a-z]/.test(tag.tag)) continue;
    if (!FAILURE_TONE.test(classText(tag.attrs.get("className")))) continue;
    const inside = childrenOf(code, tag) ?? "";
    if (FAILURE_TEXT.test(inside)) found.push(`${tag.line}: <${tag.tag}>`);
  }
  return found;
}

function offenders(): Map<string, string[]> {
  const found = new Map<string, string[]>();
  for (const file of tsxSources()) {
    if (OWNERS.some((owner) => file.startsWith(owner))) continue;
    const hits = handRolledFailures(readSource(file));
    if (hits.length > 0) found.set(file, hits);
  }
  return found;
}

describe("失败展示走 FailureCard", () => {
  const found = offenders();

  it("没有新增的手写失败展示", () => {
    const grown = [...found].filter(([file, list]) => list.length > (STOCK[file] ?? 0)).map(([file, list]) => `${file}\n    ${list.join("\n    ")}`);
    expect(grown, "用 @/components/failure/FailureCard(见本文件开头;后端那份 error / error_summary / error_detail / error_hint 用 failureFields 读)").toEqual([]);
  });

  it("存量清单没有过时的条目 —— 改好了就把它从清单里删掉", () => {
    const stale = Object.entries(STOCK).filter(([file, count]) => (found.get(file)?.length ?? 0) < count).map(([file]) => file);
    expect(stale).toEqual([]);
  });

  it("认法本身:红字配一句原因算;只给一个词上色、表单提示走 FormMessage 的不算", () => {
    expect(handRolledFailures('<p className="text-ui-xs text-destructive">{job.error}</p>')).toHaveLength(1);
    expect(handRolledFailures('<div className="bg-[color-mix(in_srgb,var(--destructive)_8%,transparent)]"><span>{run.error}</span></div>')).toHaveLength(1);
    expect(handRolledFailures('<span className="text-destructive">{t("boardNodeRunFailed")} · {reason}</span>')).toHaveLength(1);
    expect(handRolledFailures('<span className="text-destructive">{t("toolFailed")}</span>')).toHaveLength(1);
    expect(handRolledFailures('<em className="text-destructive">{runStatusText(t, run.status)}</em>')).toEqual([]);
    expect(handRolledFailures('<FailureCard title={t("wfRunFailed")} {...failureFields(job, job.error)} />')).toEqual([]);
    expect(handRolledFailures('<p className="text-muted-foreground">{job.error}</p>')).toEqual([]);
  });
});
