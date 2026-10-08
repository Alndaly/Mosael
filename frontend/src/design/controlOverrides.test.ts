/**
 * 业务代码不在控件的 className 上改**高度、留白、圆角、字号**:挑档位(`size`)和变体(`variant`),不压。
 *
 * 维护者:「很多的按钮、输入框、选择框等等的高度、风格都不一致」。刻度早就有了(components/ui/control-size.ts),
 * 参差来自调用处:`<Input className="h-8 text-ui-xs">`、`<IconButton className="h-6 w-6 rounded-full">`、
 * `<SelectTrigger className="text-xs">` —— 一处压一点,同一种控件在十个页面上就有十个样子,而且它们不跟着 token 走。
 * 规格(哪种场景用哪一档)见 docs/DESIGN_LANGUAGE.md。
 *
 * 认法:下面这些标签的 className(取里面所有字符串字面量)里,去掉 `hover:`、`max-[640px]:` 这类前缀之后,
 * 出现高度(`h-*`、`min-h-*`、`max-h-*`、`size-*`)、内边距(`p-*`、`px-*`、`py-*`、`pt-*`…)、圆角(`rounded*`)、
 * 字号(`text-ui-*`、`text-xs`…、`text-[0.8rem]` 这种写死的)。`[&_svg]:…` 这类选中**孩子**的不算(那是改里面的东西)。
 * 文本域的高度随内容,只查留白、圆角、字号。宽度、外边距、对齐、颜色不管 —— 那是排版,不是控件的样子。
 *
 * 存量按文件冻结在 STOCK 里,**只减不增**;第 3 步逐页统一时一个个改掉、把数字改小。
 */
// 这条测试是一道**棘轮**:它进 docs/CONVENTIONS.md 的清单,由 scripts/sync-ratchet-docs.py 生成。
export const RATCHET = true;
import { describe, expect, it } from "vitest";

import { classText, openTags, readSource, tsxSources } from "@/design/jsxSource";

/** 控件标签 → 查哪几样。 */
const CONTROLS: Record<string, Array<"height" | "padding" | "radius" | "font">> = {
  Button: ["height", "padding", "radius", "font"],
  IconButton: ["height", "padding", "radius", "font"],
  Input: ["height", "padding", "radius", "font"],
  SelectTrigger: ["height", "padding", "radius", "font"],
  OptionPicker: ["height", "padding", "radius", "font"],
  SearchableSelect: ["height", "padding", "radius", "font"],
  TimePicker: ["height", "padding", "radius", "font"],
  Combobox: ["height", "padding", "radius", "font"],
  Chip: ["height", "padding", "radius", "font"],
  Segmented: ["height", "padding", "radius", "font"],
  Textarea: ["padding", "radius", "font"],
  SearchInput: ["height", "padding", "radius", "font"],
  FieldBox: ["height", "padding", "radius", "font"],
  ModalSubmit: ["height", "padding", "radius", "font"],
};

const PATTERNS: Record<"height" | "padding" | "radius" | "font", RegExp> = {
  height: /^-?(?:h|min-h|max-h|size)-/,
  padding: /^-?p[xytrblse]?-/,
  radius: /^rounded(?:-|$)/,
  font: /^text-(?:ui-[\w-]+|xs|sm|base|lg|[2-9]?xl|\[\d)/,
};

/** 控件自己的家(基础组件),以及只在开发构建里的规格样张。 */
const OWNERS = ["components/ui/", "dev/"];

/**
 * 存量:`文件` → 还剩几处。只减不增。
 * IconButton 上的 `rounded-full` 多是故意的圆钮(发送、播放),`h-5 w-5` 这类多是画在缩略图角上的小钮 ——
 * 第 3 步逐页看:是该换一档的就换,真是另一种控件的就给它一个基础件。
 */
const STOCK: Record<string, number> = {
  "app/App.tsx": 3,
  "components/app/CanvasInputModeMenu.tsx": 1,
  "components/app/FailureDetails.tsx": 1,
  "components/app/image-preview.tsx": 1,
  "components/app/media-playback.tsx": 4,
  "components/app/MediaPreviewPlayer.tsx": 1,
  "components/app/TagFilter.tsx": 1,
  "components/app/TagsDialog.tsx": 1,
  "components/app/view-full-size.tsx": 1,
  "components/generation/ModelPreviewSettingsButton.tsx": 1,
  "components/jobs/JobResult.tsx": 1,
  "components/jobs/TaskCenter.tsx": 1,
  "features/admin/PricingRuleBrowser.tsx": 2,
  "features/admin/PricingTimePrices.tsx": 1,
  "features/admin/ProxySection.tsx": 1,
  "features/agent/AgentSessionSwitcher.tsx": 1,
  "features/agent/CanvasAgentChat.tsx": 5,
  "features/agent/ComposerChips.tsx": 1,
  "features/agent/ConfirmationCenter.tsx": 1,
  "features/agent/PermissionModePicker.tsx": 1,
  "features/agent/QueuedMessages.tsx": 1,
  "features/agent/skills/SkillEditorDialog.tsx": 2,
  "features/agent/SubagentPanel.tsx": 1,
  "features/agent/ToolCalls.tsx": 1,
  "features/agent/trace/TraceView.tsx": 1,
  "features/agent/VoiceDock.tsx": 2,
  "features/ai-studio/audioGeneration.tsx": 2,
  "features/ai-studio/ChatWorkspace.tsx": 3,
  "features/ai-studio/FrameSlotField.tsx": 4,
  "features/ai-studio/GenerateWorkspace.tsx": 3,
  "features/ai-studio/voicedCreation.tsx": 3,
  "features/auth/LoginView.tsx": 1,
  "features/boards/BoardCommentLayer.tsx": 1,
  "features/boards/BoardComposerShell.tsx": 1,
  "features/boards/BoardItemToolbar.tsx": 7,
  "features/boards/boardNodes.tsx": 1,
  "features/boards/BoardSelectionOutlet.tsx": 1,
  "features/boards/NodeComposer.tsx": 5,
  "features/boards/NoteComposer.tsx": 2,
  "features/boards/SequenceCell.tsx": 3,
  "features/boards/SourceAssetSlotPreview.tsx": 3,
  "features/boards/TrimComposer.tsx": 3,
  "features/browser-pool/BrowserPageList.tsx": 2,
  "features/browser-pool/BrowserPreview.tsx": 1,
  "features/browser-pool/LivePanels.tsx": 2,
  "features/browser-pool/PanelResizeHandles.tsx": 1,
  "features/browser-pool/session-tools/BrowserSessionTools.tsx": 1,
  "features/desktop/MainStaleBadge.tsx": 1,
  "features/editor/Inspector.tsx": 6,
  "features/editor/LutPicker.tsx": 2,
  "features/editor/MediaPool.tsx": 2,
  "features/editor/Monitor.tsx": 1,
  "features/editor/SubtitlePanel.tsx": 3,
  "features/editor/timeline/Timeline.tsx": 4,
  "features/editor/TranscriptPanel.tsx": 2,
  "features/entities/EntityDetail.tsx": 2,
  "features/entities/ReferenceWall.tsx": 1,
  "features/home/HomeHero.tsx": 1,
  "features/markers/AnnotationModeHint.tsx": 1,
  "features/markers/MarkerPin.tsx": 1,
  "features/media/DocumentReader.tsx": 4,
  "features/media/MediaLibraryView.tsx": 2,
  "features/nodeForms/AssetListField.tsx": 1,
  "features/nodeForms/ItemsField.tsx": 1,
  "features/nodeForms/MapField.tsx": 1,
  "features/nodeForms/StartParamsField.tsx": 3,
  "features/notes/NoteSources.tsx": 1,
  "features/plugins/ConnectionLibraries.tsx": 2,
  "features/plugins/ModelLibrary.tsx": 2,
  "features/plugins/PluginsView.tsx": 3,
  "features/plugins/workbench/ModelsPanel.tsx": 2,
  "features/plugins/workbench/RunPanel.tsx": 1,
  "features/plugins/WorkflowImport.tsx": 1,
  "features/plugins/WorkflowLibrary.tsx": 2,
  "features/plugins/WorkflowOutputs.tsx": 1,
  "features/settings/AccountSection.tsx": 1,
  "features/settings/GenerationProfileForm.tsx": 2,
  "features/settings/ModelSettingsDialog.tsx": 1,
  "features/settings/ProviderModelList.tsx": 1,
  "features/voice/VoiceCreationDialogs.tsx": 1,
  "features/workflows/NodeInspector.tsx": 4,
  "features/workflows/RunOutputs.tsx": 2,
  "features/workflows/WorkflowRunHistory.tsx": 2,
};

/** 去掉 `hover:`、`max-[640px]:`、`group-hover/x:`、`data-[state=open]:` 这类前缀和末尾的 `!`;选中孩子的(`[&_svg]:`)返回 null。 */
function baseUtility(token: string): string | null {
  let rest = token.replace(/^!/, "").replace(/!$/, "");
  for (;;) {
    const match = /^((?:[\w-]+(?:-\[[^\]]*\])?(?:\/[\w-]+)?)|\[[^\]]*\]):/.exec(rest);
    if (!match) return rest;
    if (match[1].startsWith("[")) return null;
    rest = rest.slice(match[0].length);
  }
}

export function overrides(): Map<string, string[]> {
  const found = new Map<string, string[]>();
  for (const file of tsxSources()) {
    if (OWNERS.some((owner) => file.startsWith(owner))) continue;
    const code = readSource(file);
    for (const tag of openTags(code)) {
      const checks = CONTROLS[tag.tag];
      if (!checks) continue;
      const hits = classText(tag.attrs.get("className"))
        .split(/\s+/)
        .filter(Boolean)
        .filter((token) => {
          const base = baseUtility(token);
          return base !== null && checks.some((check) => PATTERNS[check].test(base));
        });
      if (hits.length > 0) found.set(file, [...(found.get(file) ?? []), `${tag.line}: <${tag.tag}> ${[...new Set(hits)].join(" ")}`]);
    }
  }
  return found;
}

describe("控件的 className 不改高度、留白、圆角、字号", () => {
  const found = overrides();

  it("没有新增的覆盖", () => {
    const grown = [...found]
      .filter(([file, list]) => list.length > (STOCK[file] ?? 0))
      .map(([file, list]) => `${file}(存量 ${STOCK[file] ?? 0},现在 ${list.length})\n    ${list.join("\n    ")}`);
    expect(grown, "挑一档 size / variant(docs/DESIGN_LANGUAGE.md「场景 → 档位」);缺一种控件就补基础件").toEqual([]);
  });

  it("存量清单没有过时的条目 —— 改掉一处就把数字改小", () => {
    const stale = Object.entries(STOCK)
      .filter(([file, count]) => (found.get(file)?.length ?? 0) < count)
      .map(([file, count]) => `${file}: 清单 ${count},现在 ${found.get(file)?.length ?? 0}`);
    expect(stale).toEqual([]);
  });

  it("认得出:前缀剥得掉、选中孩子的不算", () => {
    expect(baseUtility("max-[640px]:h-8")).toBe("h-8");
    expect(baseUtility("group-hover/bubble:px-2")).toBe("px-2");
    expect(baseUtility("data-[state=open]:rounded-full")).toBe("rounded-full");
    expect(baseUtility("hover:bg-white!")).toBe("bg-white");
    expect(baseUtility("[&_svg]:size-3.5")).toBeNull();
    expect(PATTERNS.font.test("text-[0.8rem]")).toBe(true);
    expect(PATTERNS.font.test("text-[var(--x)]")).toBe(false);
    expect(PATTERNS.font.test("text-muted-foreground")).toBe(false);
  });
});
