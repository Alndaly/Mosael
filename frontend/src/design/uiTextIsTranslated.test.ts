/**
 * 棘轮:界面上给人看的字**走文案表**(`app/messages.ts` 的中英两份),不在组件里写死中文。
 *
 * 写死的中文在英文界面里原样出现 —— 3D 场景页的「已选 N 个场景」「删除所选」、Blender 取回的
 * 提示、桌面壳的菜单和托盘,切成英文后还是中文。
 *
 * 扫的是代码行里的中文字符(跳过注释)。`LEFT` 是存量,**只减不增**:哪个文件翻完了就把它
 * 删掉或改小。`EXEMPT` 是**本来就该是中文**的文件,每一条写清为什么(匹配平台页面上的中文按钮、
 * 发给模型的提示词、古诗……);不许拿它当垃圾桶。
 *
 * 看不见的:拼在模板里、从后端来的字。后端那一半见 backend/tests/test_user_facing_errors_are_translated.py。
 */
// 这条测试是一道**棘轮**:它进 docs/CONVENTIONS.md 的清单,由 scripts/sync-ratchet-docs.py 生成。
export const RATCHET = true;

import { readFileSync, readdirSync, statSync } from "node:fs";
import { join, relative } from "node:path";
import { expect, it } from "vitest";

const REPO = join(import.meta.dirname, "..", "..", "..");
const ROOTS = ["frontend/src", "electron", "browser-extension/src"];
const CJK = /[一-鿿]/;
const SKIP_FILE = /(\.test\.|\.d\.ts$|\.bundle\.cjs$|\/generated\/|app\/messages\.ts$)/;

function* files(dir: string): Generator<string> {
  for (const name of readdirSync(dir)) {
    if (name === "node_modules" || name === "dist") continue;
    const path = join(dir, name);
    if (statSync(path).isDirectory()) yield* files(path);
    else if (/\.(tsx?|cjs|mjs|js)$/.test(name)) yield path;
  }
}

function count(): Map<string, number> {
  const found = new Map<string, number>();
  for (const root of ROOTS) {
    for (const path of files(join(REPO, root))) {
      const key = relative(REPO, path);
      if (SKIP_FILE.test(key)) continue;
      let n = 0;
      for (const raw of readFileSync(path, "utf8").split("\n")) {
        const line = raw.trim();
        if (/^(\/\/|\*|\/\*|\{\/\*)/.test(line)) continue;
        const code = line.replace(/\/\/.*$/, "").replace(/\{\/\*.*?\*\/\}/g, "").replace(/\/\*.*?\*\//g, "");
        if (CJK.test(code)) n += 1;
      }
      if (n) found.set(key, n);
    }
  }
  return found;
}

/** 本来就该是中文的文件。每条写清理由。 */
const EXEMPT = new Map<string, string>([
]);

/** 还没翻完的:文件 → 还剩几行。**只减不增。** */
const LEFT = new Map<string, number>([
  ["browser-extension/src/capture.ts", 3],
  ["browser-extension/src/content.ts", 5],
  ["browser-extension/src/i18n.ts", 56],
  ["browser-extension/src/mosael/client.ts", 5],
  ["browser-extension/src/page-bridge.ts", 7],
  ["browser-extension/src/platforms/bilibili.ts", 5],
  ["browser-extension/src/platforms/labels.ts", 1],
  ["browser-extension/src/platforms/youtube.ts", 4],
  ["browser-extension/src/sidepanel.tsx", 5],
  ["browser-extension/src/video-frame.ts", 2],
  ["electron/brand-dev.cjs", 2],
  ["electron/main.cjs", 46],
  ["electron/publish/adapters/bilibili.ts", 20],
  ["electron/publish/adapters/douyin.ts", 5],
  ["electron/publish/adapters/shared.ts", 4],
  ["electron/publish/adapters/tiktok.ts", 8],
  ["electron/publish/adapters/weixinChannels.ts", 6],
  ["electron/publish/adapters/xiaohongshu.ts", 12],
  ["electron/publish/adapters/youtube.ts", 7],
  ["electron/publish/browserActions.ts", 9],
  ["electron/publish/clickChain.ts", 3],
  ["electron/publish/pageDriver.ts", 1],
  ["electron/publish/platforms.ts", 10],
  ["electron/publish/publishWorker.ts", 19],
  ["electron/publish/selectors.ts", 48],
  ["electron/system/customCss.ts", 3],
  ["electron/system/index.ts", 2],
  ["electron/system/power.ts", 2],
  ["electron/system/protocol.ts", 1],
  ["electron/system/shortcuts.ts", 2],
  ["electron/system/tray.ts", 6],
  ["electron/webauthn.cjs", 7],
  ["frontend/src/api/transport.ts", 1],
  ["frontend/src/app/App.tsx", 4],
  ["frontend/src/app/PageBoundary.tsx", 2],
  ["frontend/src/app/appearance.tsx", 8],
  ["frontend/src/app/customCss.tsx", 1],
  ["frontend/src/app/mutationErrors.ts", 1],
  ["frontend/src/components/app/CanvasInputModeSwitch.tsx", 2],
  ["frontend/src/components/app/bulkSelection.tsx", 3],
  ["frontend/src/components/app/canvasTitle.tsx", 1],
  ["frontend/src/components/app/combobox.tsx", 5],
  ["frontend/src/components/app/image-preview.tsx", 1],
  ["frontend/src/components/layout/AppShell.tsx", 9],
  ["frontend/src/components/layout/CommandPalette.tsx", 1],
  ["frontend/src/components/layout/InspectorCard.tsx", 5],
  ["frontend/src/components/layout/NotificationCenter.tsx", 9],
  ["frontend/src/components/layout/TaskCenter.tsx", 7],
  ["frontend/src/components/markdown/links.ts", 2],
  ["frontend/src/components/settings/settings-layout.tsx", 5],
  ["frontend/src/components/ui/form.tsx", 3],
  ["frontend/src/components/ui/option-picker.tsx", 3],
  ["frontend/src/components/ui/searchable-select.tsx", 13],
  ["frontend/src/components/ui/select.tsx", 2],
  ["frontend/src/domain/timeline/transcriptProjection.ts", 1],
  ["frontend/src/features/admin/AdminView.tsx", 5],
  ["frontend/src/features/agent/CanvasAgentChat.tsx", 7],
  ["frontend/src/features/agent/ChatBubble.tsx", 3],
  ["frontend/src/features/agent/ChatComposer.tsx", 2],
  ["frontend/src/features/agent/ComposerChips.tsx", 1],
  ["frontend/src/features/agent/ConfirmationCenter.tsx", 1],
  ["frontend/src/features/agent/InlineConfirmations.tsx", 2],
  ["frontend/src/features/agent/PermissionBadge.tsx", 1],
  ["frontend/src/features/agent/PermissionModePicker.tsx", 1],
  ["frontend/src/features/agent/SessionSettingsMenu.tsx", 3],
  ["frontend/src/features/agent/SubagentPanel.tsx", 2],
  ["frontend/src/features/agent/ToolCalls.tsx", 7],
  ["frontend/src/features/agent/VoiceDock.tsx", 1],
  ["frontend/src/features/agent/spokenChoice.ts", 6],
  ["frontend/src/features/agent/toolResultShapes.tsx", 47],
  ["frontend/src/features/agent/trace/TraceView.tsx", 3],
  ["frontend/src/features/agent/useVoiceLoop.ts", 10],
  ["frontend/src/features/agent/userMessage.tsx", 2],
  ["frontend/src/features/ai-studio/AiStudio.tsx", 15],
  ["frontend/src/features/ai-studio/ChatWorkspace.tsx", 29],
  ["frontend/src/features/ai-studio/SessionList.tsx", 5],
  ["frontend/src/features/auth/LoginView.tsx", 6],
  ["frontend/src/features/auth/legal.tsx", 14],
  ["frontend/src/features/boards/AudioComposer.tsx", 2],
  ["frontend/src/features/boards/BoardCanvas.tsx", 11],
  ["frontend/src/features/boards/BoardsView.tsx", 4],
  ["frontend/src/features/boards/NodeComposer.tsx", 12],
  ["frontend/src/features/boards/NoteComposer.tsx", 6],
  ["frontend/src/features/boards/PromptEditor.tsx", 4],
  ["frontend/src/features/boards/TrimComposer.tsx", 2],
  ["frontend/src/features/boards/boardNodes.tsx", 4],
  ["frontend/src/features/browser-pool/BrowserPoolView.tsx", 5],
  ["frontend/src/features/collaboration/CollaborationSheet.tsx", 3],
  ["frontend/src/features/collaboration/CommentContent.tsx", 2],
  ["frontend/src/features/editor/EditorView.tsx", 2],
  ["frontend/src/features/editor/Inspector.tsx", 5],
  ["frontend/src/features/editor/MediaPool.tsx", 3],
  ["frontend/src/features/editor/Monitor.tsx", 11],
  ["frontend/src/features/editor/SubtitleDub.tsx", 2],
  ["frontend/src/features/editor/SubtitlePanel.tsx", 14],
  ["frontend/src/features/editor/TranscriptPanel.tsx", 7],
  ["frontend/src/features/editor/subtitleStyle.ts", 1],
  ["frontend/src/features/editor/textStyle.ts", 5],
  ["frontend/src/features/editor/timeline/Timeline.tsx", 3],
  ["frontend/src/features/editor/timeline/TimelineClip.tsx", 1],
  ["frontend/src/features/editor/transcriptSpeakers.ts", 1],
  ["frontend/src/features/home/HomeView.tsx", 1],
  ["frontend/src/features/home/poems.ts", 24],
  ["frontend/src/features/media/AssetCompareView.tsx", 4],
  ["frontend/src/features/media/AssetPreviewModal.tsx", 1],
  ["frontend/src/features/media/DenoiseDialog.tsx", 1],
  ["frontend/src/features/media/MediaLibraryView.tsx", 10],
  ["frontend/src/features/media/Recorder.tsx", 1],
  ["frontend/src/features/notes/NoteEditor.tsx", 1],
  ["frontend/src/features/notes/NotesView.tsx", 1],
  ["frontend/src/features/notes/noteNodeUI.ts", 11],
  ["frontend/src/features/notes/strings.ts", 25],
  ["frontend/src/features/notes/useNoteAttachments.tsx", 1],
  ["frontend/src/features/plugins/PluginMarket.tsx", 7],
  ["frontend/src/features/plugins/PluginsView.tsx", 30],
  ["frontend/src/features/scenes/SceneAxisGizmo.tsx", 1],
  ["frontend/src/features/scenes/SceneBlender.tsx", 49],
  ["frontend/src/features/scenes/SceneBlenderPull.tsx", 15],
  ["frontend/src/features/scenes/SceneCameraPanel.tsx", 31],
  ["frontend/src/features/scenes/SceneHistory.tsx", 4],
  ["frontend/src/features/scenes/SceneInspector.tsx", 55],
  ["frontend/src/features/scenes/SceneList.tsx", 33],
  ["frontend/src/features/scenes/SceneStudio.tsx", 182],
  ["frontend/src/features/scenes/SceneViewport.tsx", 14],
  ["frontend/src/features/scenes/axisGizmo.ts", 3],
  ["frontend/src/features/scenes/blockoutPrompt.ts", 7],
  ["frontend/src/features/scenes/encodeVideo.ts", 3],
  ["frontend/src/features/scenes/lighting.ts", 55],
  ["frontend/src/features/scenes/sceneGraph.ts", 19],
  ["frontend/src/features/scheduler/SchedulerView.tsx", 4],
  ["frontend/src/features/scheduler/boundWorkflowRow.tsx", 5],
  ["frontend/src/features/settings/AgentMemorySection.tsx", 3],
  ["frontend/src/features/settings/AgentVoiceSection.tsx", 1],
  ["frontend/src/features/settings/AppearanceSection.tsx", 4],
  ["frontend/src/features/settings/AsrModelsSection.tsx", 8],
  ["frontend/src/features/settings/BuiltinTtsSection.tsx", 1],
  ["frontend/src/features/settings/FeishuSection.tsx", 3],
  ["frontend/src/features/settings/GenerationProfileForm.tsx", 34],
  ["frontend/src/features/settings/ModelSettingsDialog.tsx", 27],
  ["frontend/src/features/settings/ProviderModelList.tsx", 11],
  ["frontend/src/features/settings/ProviderOAuthDialog.tsx", 2],
  ["frontend/src/features/settings/ProviderPricingSection.tsx", 1],
  ["frontend/src/features/settings/ProviderProfilesSection.tsx", 21],
  ["frontend/src/features/settings/ProviderQuota.tsx", 2],
  ["frontend/src/features/settings/SeparationEnginesSection.tsx", 2],
  ["frontend/src/features/settings/SettingsView.tsx", 1],
  ["frontend/src/features/settings/VoiceCloneSection.tsx", 19],
  ["frontend/src/features/settings/VoiceLibrarySection.tsx", 3],
  ["frontend/src/features/statistics/StatisticsCharts.tsx", 5],
  ["frontend/src/features/statistics/StatisticsView.tsx", 2],
  ["frontend/src/features/voice/SpeechVoiceFields.tsx", 5],
  ["frontend/src/features/voice/VoiceLibrary.tsx", 1],
  ["frontend/src/features/workflows/MapField.tsx", 7],
  ["frontend/src/features/workflows/RunOutputs.tsx", 1],
  ["frontend/src/features/workflows/WorkflowCommunityDialog.tsx", 5],
  ["frontend/src/features/workflows/WorkflowNode.tsx", 13],
  ["frontend/src/features/workflows/WorkflowRunHistory.tsx", 7],
  ["frontend/src/features/workflows/WorkflowsView.tsx", 39],
  ["frontend/src/features/workflows/collapse.ts", 1],
]);

it("没有新的写死中文的界面文字", () => {
  const grown = [...count()].filter(([file, n]) => !EXEMPT.has(file) && n > (LEFT.get(file) ?? 0));
  expect(grown.map(([f, n]) => `${f}: ${LEFT.get(f) ?? 0} → ${n}`), "界面文字走 app/messages.ts(中英两份)").toEqual([]);
});

it("存量只减不增", () => {
  const now = count();
  const stale = [...LEFT].filter(([file, n]) => (now.get(file) ?? 0) < n);
  expect(stale.map(([f, n]) => `${f}: ${n} → ${now.get(f) ?? 0}`), "翻掉了一些:把 LEFT 里的数字改小(0 就删掉)").toEqual([]);
});

it("豁免的文件真的存在,且不和存量重复", () => {
  const now = count();
  for (const file of EXEMPT.keys()) {
    expect(now.has(file), `${file} 已经没有中文了,从 EXEMPT 里删掉`).toBe(true);
    expect(LEFT.has(file), `${file} 同时在 EXEMPT 和 LEFT 里`).toBe(false);
  }
});
