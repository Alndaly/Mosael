/**
 * 不手写原生 `<button>` 拼一个按钮,不自己画下拉触发器。
 *
 * 维护者:「很多的按钮、输入框、选择框等等的高度、风格都不一致」。一大半出在这里:一个 `<button>` 加一串 class
 * (高度、底色、悬停、圆角、焦点圈一样一样抄)就是一颗「看着像按钮」的东西,它不跟档位、不跟 token,也不接
 * `loading`、`disabledReason`、悬停说明;一个 `<button>` 套上输入框的描边和一个向下箭头就是一个「看着像下拉」的东西,
 * 并排放在真下拉旁边,圆角、箭头、留白各差一点。规格见 docs/DESIGN_LANGUAGE.md「按钮」「字段」。
 *
 * 该用什么:
 * - 按钮 → `Button` / `IconButton`;分段 → `Segmented`(或 segmentedListClass / segmentedItemClass);胶囊筛选 → `Chip`;
 *   单选 → `RadioGroup`;页签 → `Tabs` / `CollectionTabs`;菜单里的一行 → `MenuItem`;
 * - 选一个值 → `Select` / `OptionPicker` / `SearchableSelect` / `Combobox` / `TimePicker`(它们的触发器同一种样子);
 *   长得像字段、却不是下拉的一格(只读的值、取色条)→ `FieldBox`;搜索框 → `SearchInput`。
 *
 * 两条都**按文件冻结**存量,只减不增:
 * - 原生 `<button>`:components/ui(基础组件自己)以外,每个文件还剩几个;
 * - 自画的下拉触发器:基础组件以外用了 `fieldTriggerClass` / `FIELD_TRIGGER_CHEVRON`,或者一个按钮套着输入框的描边 / 底色
 *   (`border-field-border` / `bg-field`)又放了向下的箭头。
 */
// 这条测试是一道**棘轮**:它进 docs/CONVENTIONS.md 的清单,由 scripts/sync-ratchet-docs.py 生成。
export const RATCHET = true;
import { describe, expect, it } from "vitest";

import { childrenOf, classText, openTags, readSource, tsxSources } from "@/design/jsxSource";

const OWNERS = ["components/ui/", "dev/"];

/** 原生 `<button>`:`文件` → 还剩几个。只减不增。 */
const NATIVE_STOCK: Record<string, number> = {
  "components/app/asset-preview.tsx": 2,
  "components/app/AssetGridPicker.tsx": 2,
  "components/app/CanvasNodeSearch.tsx": 1,
  "components/app/canvasPendingLink.tsx": 1,
  "components/app/CatalogDialog.tsx": 1,
  "components/app/combobox.tsx": 1,
  "components/app/ConfigNotice.tsx": 2,
  "components/app/LibraryBrowser.tsx": 3,
  "components/app/PickListDialog.tsx": 1,
  "components/app/PromptTemplates.tsx": 2,
  "components/app/RangePicker.tsx": 1,
  "components/app/ServerPicker.tsx": 3,
  "components/app/TagFilter.tsx": 2,
  "components/generation/ModelPreviewSettingsButton.tsx": 1,
  "components/jobs/JobChildren.tsx": 1,
  "components/jobs/NotificationCenter.tsx": 3,
  "components/layout/AppShell.tsx": 8,
  "components/layout/InspectorCard.tsx": 1,
  "components/layout/StudioPage.tsx": 1,
  "features/admin/PricingRuleBrowser.tsx": 2,
  "features/agent/AgentSessionSwitcher.tsx": 2,
  "features/agent/CanvasAgentChat.tsx": 1,
  "features/agent/ChatComposer.tsx": 2,
  "features/agent/ComposerChips.tsx": 1,
  "features/agent/ConfirmationCard.tsx": 1,
  "features/agent/ContextMeter.tsx": 2,
  "features/agent/InlineQuestions.tsx": 1,
  "features/agent/messageUsage.tsx": 1,
  "features/agent/NoteEditPreview.tsx": 1,
  "features/agent/skills/SkillCardPreviews.tsx": 1,
  "features/agent/skills/SkillContent.tsx": 1,
  "features/agent/SpeakButton.tsx": 1,
  "features/agent/stickToBottom.tsx": 1,
  "features/agent/SubagentPanel.tsx": 3,
  "features/agent/ToolCalls.tsx": 3,
  "features/agent/toolResultShapes.tsx": 2,
  "features/agent/trace/TraceView.tsx": 4,
  "features/ai-studio/AiStudio.tsx": 1,
  "features/ai-studio/ChatWorkspace.tsx": 4,
  "features/ai-studio/FrameSlotField.tsx": 2,
  "features/ai-studio/GenerateWorkspace.tsx": 2,
  "features/ai-studio/SessionList.tsx": 1,
  "features/ai-studio/voicedCreation.tsx": 2,
  "features/auth/LoginView.tsx": 4,
  "features/boards/AbilityComposer.tsx": 1,
  "features/boards/BoardCommentLayer.tsx": 1,
  "features/boards/BoardComposerShell.tsx": 1,
  "features/boards/BoardItemToolbar.tsx": 3,
  "features/boards/boardNodes.tsx": 2,
  "features/boards/BoardsView.tsx": 2,
  "features/boards/PromptEditor.tsx": 2,
  "features/boards/SceneReferencePicker.tsx": 1,
  "features/boards/TrimComposer.tsx": 1,
  "features/browser-pool/BrowserPageList.tsx": 2,
  "features/browser-pool/PanelTitle.tsx": 1,
  "features/browser-pool/session-tools/BrowserSessionTools.tsx": 2,
  "features/browser-pool/session-tools/ImagePanel.tsx": 1,
  "features/collaboration/CommentComposer.tsx": 1,
  "features/collaboration/commentDocument.tsx": 1,
  "features/editor/ClipAppearancePanel.tsx": 2,
  "features/editor/CurveEditor.tsx": 2,
  "features/editor/EditorView.tsx": 1,
  "features/editor/FillerPicker.tsx": 1,
  "features/editor/Inspector.tsx": 11,
  "features/editor/MediaPool.tsx": 1,
  "features/editor/Monitor.tsx": 1,
  "features/editor/SequenceSettings.tsx": 2,
  "features/editor/SubtitleFiles.tsx": 2,
  "features/editor/SubtitlePanel.tsx": 7,
  "features/editor/timeline/Timeline.tsx": 4,
  "features/editor/TranscriptPanel.tsx": 12,
  "features/entities/AssetEntities.tsx": 1,
  "features/entities/DrawDialog.tsx": 1,
  "features/entities/EntityCard.tsx": 1,
  "features/entities/EntityDetail.tsx": 2,
  "features/entities/EntityMention.tsx": 1,
  "features/entities/ReferenceWall.tsx": 1,
  "features/entities/SpeakDialog.tsx": 1,
  "features/home/HomeView.tsx": 2,
  "features/markers/MarkerPin.tsx": 1,
  "features/markers/ShortcutRecorder.tsx": 1,
  "features/media/AssetCompareView.tsx": 1,
  "features/media/AssetLineage.tsx": 1,
  "features/media/AssetPreviewModal.tsx": 3,
  "features/media/DenoiseDialog.tsx": 2,
  "features/media/DocumentReader.tsx": 1,
  "features/media/MediaLibraryView.tsx": 1,
  "features/media/Recorder.tsx": 1,
  "features/media/UrlImportDialog.tsx": 1,
  "features/nodeForms/NodeConfigForm.tsx": 2,
  "features/nodeForms/RefEditor.tsx": 1,
  "features/notes/NoteEditor.tsx": 1,
  "features/notes/NoteFormatToolbar.tsx": 3,
  "features/notes/NoteHistoryDialog.tsx": 3,
  "features/notes/NoteList.tsx": 1,
  "features/notes/NoteSources.tsx": 2,
  "features/notes/NotesView.tsx": 6,
  "features/notes/SaveToNote.tsx": 2,
  "features/notes/TableSizePicker.tsx": 1,
  "features/notes/useNoteAttachments.tsx": 1,
  "features/plugins/appForm/FormsBar.tsx": 1,
  "features/plugins/ConnectionLocalService.tsx": 4,
  "features/plugins/ModelDetail.tsx": 2,
  "features/plugins/ModelLibrary.tsx": 2,
  "features/plugins/PluginsView.tsx": 3,
  "features/plugins/ProvidedModels.tsx": 1,
  "features/plugins/ToolRowFrame.tsx": 1,
  "features/plugins/workbench/AssistantPanel.tsx": 1,
  "features/plugins/workbench/ModelDownload.tsx": 1,
  "features/plugins/workbench/ModelsPanel.tsx": 2,
  "features/plugins/workbench/RunPanel.tsx": 1,
  "features/plugins/workbench/WorkbenchTabs.tsx": 1,
  "features/plugins/WorkflowAppEditor.tsx": 1,
  "features/plugins/WorkflowLibrary.tsx": 3,
  "features/publish/PublishView.tsx": 3,
  "features/scenes/SceneAxisGizmo.tsx": 1,
  "features/scenes/SceneBlender.tsx": 2,
  "features/scenes/SceneBlenderPull.tsx": 1,
  "features/scenes/SceneCameraPanel.tsx": 3,
  "features/scenes/SceneDopeSheet.tsx": 1,
  "features/scenes/SceneList.tsx": 1,
  "features/scenes/ScenePanel.tsx": 1,
  "features/scenes/SceneStudio.tsx": 9,
  "features/scenes/SceneViewport.tsx": 1,
  "features/scheduler/SchedulerView.tsx": 2,
  "features/settings/AgentSkillsSection.tsx": 1,
  "features/settings/AppearanceSection.tsx": 1,
  "features/settings/ModelSettingsDialog.tsx": 1,
  "features/settings/ProviderHealth.tsx": 1,
  "features/settings/ProviderOAuthDialog.tsx": 1,
  "features/settings/ProviderProfilesSection.tsx": 1,
  "features/settings/SettingsView.tsx": 2,
  "features/statistics/StatisticsCharts.tsx": 2,
  "features/statistics/StatisticsView.tsx": 2,
  "features/voice/VoiceList.tsx": 2,
  "features/workflows/NodeInspector.tsx": 2,
  "features/workflows/nodeInspectorGenerate.tsx": 1,
  "features/workflows/WorkflowComments.tsx": 1,
  "features/workflows/WorkflowEditor.tsx": 1,
  "features/workflows/WorkflowEditorToolbar.tsx": 2,
  "features/workflows/WorkflowRunHistory.tsx": 3,
  "features/workflows/WorkflowsView.tsx": 1,
  "test/pageTrail.tsx": 3,
};

/** 自画的下拉触发器:`文件` → 还剩几个。只减不增。 */
const TRIGGER_STOCK: Record<string, number> = {};

export function nativeButtons(): Map<string, number[]> {
  const found = new Map<string, number[]>();
  for (const file of tsxSources()) {
    if (OWNERS.some((owner) => file.startsWith(owner))) continue;
    for (const tag of openTags(readSource(file))) {
      if (tag.tag === "button") found.set(file, [...(found.get(file) ?? []), tag.line]);
    }
  }
  return found;
}

const FIELD_LOOK = /(?:^|\s)(?:[\w-]+:)*(?:border-field-border|bg-field)(?=\s|$)/;

/** 自己就是一种下拉的基础件(不在 components/ui 里的):组合框(能选清单里的,也能手填)。 */
const TRIGGER_OWNERS = ["components/app/combobox.tsx"];

export function drawnTriggers(): Map<string, string[]> {
  const found = new Map<string, string[]>();
  const add = (file: string, what: string) => found.set(file, [...(found.get(file) ?? []), what]);
  for (const file of tsxSources()) {
    if (OWNERS.some((owner) => file.startsWith(owner)) || TRIGGER_OWNERS.includes(file)) continue;
    const code = readSource(file);
    code.split("\n").forEach((line, index) => {
      if (/\b(?:fieldTriggerClass|FIELD_TRIGGER_CHEVRON)\b/.test(line) && !/^\s*import\b/.test(line)) add(file, `${index + 1}: fieldTriggerClass`);
    });
    for (const tag of openTags(code)) {
      if (tag.tag !== "button" && tag.tag !== "Button") continue;
      if (!FIELD_LOOK.test(classText(tag.attrs.get("className")))) continue;
      if (/<Chevron(?:Down|sUpDown)\b/.test(childrenOf(code, tag) ?? "")) add(file, `${tag.line}: <${tag.tag}> 输入框的描边 + 向下箭头`);
    }
  }
  return found;
}

function grownAgainst<T>(found: Map<string, T[]>, stock: Record<string, number>): string[] {
  return [...found]
    .filter(([file, list]) => list.length > (stock[file] ?? 0))
    .map(([file, list]) => `${file}(存量 ${stock[file] ?? 0},现在 ${list.length}):${list.join(", ")}`);
}

function staleAgainst<T>(found: Map<string, T[]>, stock: Record<string, number>): string[] {
  return Object.entries(stock)
    .filter(([file, count]) => (found.get(file)?.length ?? 0) < count)
    .map(([file, count]) => `${file}: 清单 ${count},现在 ${found.get(file)?.length ?? 0}`);
}

describe("不手写原生按钮", () => {
  const found = nativeButtons();

  it("没有新增的原生 <button>(用 Button / IconButton / Segmented / Chip / MenuItem …)", () => {
    expect(grownAgainst(found, NATIVE_STOCK)).toEqual([]);
  });

  it("存量清单没有过时的条目 —— 换掉一个就把数字改小", () => {
    expect(staleAgainst(found, NATIVE_STOCK)).toEqual([]);
  });
});

describe("不自己画下拉触发器", () => {
  const found = drawnTriggers();

  it("没有新增的自画触发器(用 Select / OptionPicker / SearchableSelect / Combobox)", () => {
    expect(grownAgainst(found, TRIGGER_STOCK)).toEqual([]);
  });

  it("存量清单没有过时的条目", () => {
    expect(staleAgainst(found, TRIGGER_STOCK)).toEqual([]);
  });
});
