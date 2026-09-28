import React from "react";

import type { Workspace } from "@/api/client";
import { useI18n } from "@/app/preferences";
import { SEGMENTED_LIST, segmentedTriggerClass } from "@/components/ui/tabs";
import { AudioWorkspace } from "@/features/ai-studio/AudioWorkspace";
import { ChatWorkspace } from "@/features/ai-studio/ChatWorkspace";
import { GenerateWorkspace } from "@/features/ai-studio/GenerateWorkspace";
import { usePersistentTab } from "@/lib/usePersistentTab";

//: 三页:对话;「生成」是图像和视频(按会话迭代,同一个提示词改几轮);「音频」是朗读、播客和音乐 / 音效 ——
//: 找音乐的人会进「音频」,所以音乐、音效模型在那一页,不混在图像视频的选择器里。
const STUDIO_TABS = ["chat", "generate", "audio"] as const;
type StudioTab = (typeof STUDIO_TABS)[number];
const STUDIO_TAB_LABELS = { chat: "aiTabChat", generate: "aiTabGenerate", audio: "aiTabAudio" } as const;

export function AiStudio({ workspace }: { workspace: Workspace }) {
  const t = useI18n();
  const [tab, setTab] = usePersistentTab<StudioTab>("ai-studio", "chat", STUDIO_TABS);

  const switcher = (
    <div className={SEGMENTED_LIST} role="tablist" aria-label="AI Studio">
      {STUDIO_TABS.map((item) => (
        <button
          key={item}
          type="button"
          role="tab"
          aria-selected={tab === item}
          className={segmentedTriggerClass(tab === item)}
          onClick={() => setTab(item)}
        >
          {t(STUDIO_TAB_LABELS[item])}
        </button>
      ))}
    </div>
  );

  return (
    // 聊天/生成只在线程内部滚动,页面本身不滚(overflow-hidden)。
    <div className="flex h-full min-h-0 flex-col items-stretch overflow-hidden bg-workspace-panel">
      {tab === "chat" ? (
        <ChatWorkspace workspace={workspace} switcher={switcher} />
      ) : tab === "generate" ? (
        <GenerateWorkspace workspace={workspace} medium="visual" switcher={switcher} />
      ) : (
        <AudioWorkspace workspace={workspace} switcher={switcher} />
      )}
    </div>
  );
}
