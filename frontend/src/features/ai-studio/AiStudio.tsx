import React from "react";

import type { Workspace } from "@/api/client";
import { useI18n } from "@/app/preferences";
import { segmentedItemClass, segmentedListClass } from "@/components/ui/segmented";
import { ChatWorkspace } from "@/features/ai-studio/ChatWorkspace";
import { GenerateWorkspace } from "@/features/ai-studio/GenerateWorkspace";
import {
  CREATION_FILTER_EVENT,
  OPEN_CREATION_SESSION_EVENT,
  STUDIO_TABS,
  STUDIO_TAB_KEY,
  parseAiStudioHash,
  type StudioTab,
} from "@/lib/aiStudioLink";
import { emitOpenEvent, hasPendingOpenRequest } from "@/lib/deepLink";
import { usePersistentTab } from "@/lib/usePersistentTab";

//: 两个分区(ADR 0055):对话;创作是图像、视频、语音、播客、音乐一个工作台 —— 会话列表上面一排筛选,种类由挑的模型定。
const STUDIO_TAB_LABELS = { chat: "aiTabChat", create: "aiTabCreate" } as const;

export function AiStudio({ workspace }: { workspace: Workspace }) {
  const t = useI18n();
  const [tab, setTab] = usePersistentTab<StudioTab>(STUDIO_TAB_KEY, "chat", STUDIO_TABS);
  useStudioLink(setTab);

  const switcher = (
    <div className={segmentedListClass()} role="tablist" aria-label="AI Studio">
      {STUDIO_TABS.map((item) => (
        <button
          key={item}
          type="button"
          role="tab"
          aria-selected={tab === item}
          className={segmentedItemClass(tab === item)}
          onClick={() => setTab(item)}
        >
          {t(STUDIO_TAB_LABELS[item])}
        </button>
      ))}
    </div>
  );

  return (
    // 聊天/创作只在线程内部滚动,页面本身不滚(overflow-hidden)。
    <div className="flex h-full min-h-0 flex-col items-stretch overflow-hidden bg-workspace-panel">
      {tab === "chat" ? (
        <ChatWorkspace workspace={workspace} switcher={switcher} />
      ) : (
        <GenerateWorkspace workspace={workspace} switcher={switcher} />
      )}
    </div>
  );
}

/**
 * 深链(lib/aiStudioLink):`#/ai?tab=…&session=…&kind=…` 当场切分区,会话和筛选交给信箱,然后把地址还原成 `#/ai` —— 读了不清,
 * 它就一直留在地址里,下一次别的原因重读时把人拽回去。挂载时读一次,之后 hash 再变(人已经在这一页上)也读。
 *
 * 别处直接发来的「打开这条创作会话」(任务中心「前往」、mosael://ai/<id>)不经过地址:看见信箱里有、或者正好发来,切到创作分区,
 * 由里面的创作页去取。
 */
function useStudioLink(setTab: (tab: StudioTab) => void) {
  const set = React.useRef(setTab);
  set.current = setTab;
  React.useEffect(() => {
    const take = () => {
      const link = parseAiStudioHash(window.location.hash);
      if (!link || (!link.tab && !link.session && !link.kind)) return;
      window.history.replaceState(null, "", "#/ai");
      if (link.tab) set.current(link.tab);
      else if (link.session || link.kind) set.current("create");
      if (link.kind) emitOpenEvent(CREATION_FILTER_EVENT, link.kind);
      if (link.session) emitOpenEvent(OPEN_CREATION_SESSION_EVENT, link.session);
    };
    const toCreate = () => set.current("create");
    take();
    if (hasPendingOpenRequest(OPEN_CREATION_SESSION_EVENT) || hasPendingOpenRequest(CREATION_FILTER_EVENT)) toCreate();
    window.addEventListener("hashchange", take);
    window.addEventListener(OPEN_CREATION_SESSION_EVENT, toCreate);
    window.addEventListener(CREATION_FILTER_EVENT, toCreate);
    return () => {
      window.removeEventListener("hashchange", take);
      window.removeEventListener(OPEN_CREATION_SESSION_EVENT, toCreate);
      window.removeEventListener(CREATION_FILTER_EVENT, toCreate);
    };
  }, []);
}
