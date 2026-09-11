import { toast } from "sonner";

import { assetFileUrl, type Asset } from "@/api/client";
import { api } from "@/api/transport";
import { useI18n } from "@/app/preferences";
import { useImagePreview } from "@/components/app/image-preview";
import { gotoRecord } from "@/lib/deepLink";
import type { AgentReference, ReferenceKind } from "@/features/agent/references";

/**
 * 每一类去哪儿问"它还在不在",在的话跳哪儿,以及**跳过去之后靠什么把那条记录打开**。
 *
 * `event` 不是可选的装饰:改 `location.hash` 只在**目标页还没挂载**时够用 —— 那时页面挂载、
 * 读一遍 hash、把记录打开。而人已经在那一页上时(正开着画板 A,点了画板 B 的引用),
 * hash 变了却没有任何东西去重读它:`location.hash` 不是响应式的,那个 effect 的依赖里也没有它。
 * 结果就是点了没反应。
 *
 * 仓库里本来就有这条通道(lib/deepLink 的 gotoRecord + 三连发),画板和工作流也早就在听
 * 对应的事件了 —— 这里此前绕过它直接写 hash,才把自己关在了"只有跨页才灵"的一半里。
 * 笔记不需要事件:NotesView 自己听着 hashchange。
 */
const ROUTES: Record<ReferenceKind, { probe: (id: string) => string; href?: (id: string) => string; event?: string }> = {
  asset: { probe: (id) => `/api/assets/${id}` },
  note: { probe: (id) => `/api/notes/${id}`, href: (id) => `#/notes?note=${encodeURIComponent(id)}` },
  board: {
    probe: (id) => `/api/boards/${id}`,
    href: (id) => `#/boards?board=${encodeURIComponent(id)}`,
    event: "mosael:open-board",
  },
  workflow: {
    probe: (id) => `/api/workflows/${id}`,
    href: (id) => `#/workflows?workflow=${encodeURIComponent(id)}`,
    event: "mosael:open-workflow",
  },
};

/**
 * 点开一个引用。
 *
 * ## 「它还不在」这件事**只在点下去的那一刻才需要知道**
 *
 * 想让已删掉的胶囊看起来就不一样,就得在渲染时逐个去查 —— 而一屏几十条消息、每条几个引用,
 * 那是几百次请求,其中绝大多数的答案从来没人用到。发送时记一份"当时还在"更没用:常见的情形
 * 恰恰是**发出去之后**才被删,快照永远说"当时还在"。
 *
 * 所以不预判,点的时候现问:在就打开,不在就直说。代价只发生在真的有人点它的时候。
 *
 * ## 不在的时候要**出声**
 *
 * 此前素材那条是 `.catch(() => null); if (!asset) return;` —— 点了什么都不发生,读起来就是
 * "这个按钮坏了";而笔记/画板/工作流干脆不问,直接改 hash,于是跳进一个空页面。两种都比
 * 一句"它已经不在了"糟。
 *
 * ## 各类的"打开"本来就不一样
 *
 * 素材有画面 → 全局灯箱(那里已经有翻页、Esc 和层级);笔记、画板、工作流是**页面** ——
 * 塞进一个小弹层里只能看个开头,而它们本来就有自己的完整界面。
 */
export function useReferencePreview() {
  const t = useI18n();
  const { openImagePreview } = useImagePreview();
  return async (reference: AgentReference) => {
    const route = ROUTES[reference.kind];
    if (!route) return;
    const found = await api<Asset | unknown>(route.probe(reference.id)).catch(() => null);
    if (!found) {
      toast.error(t("agentRefGone").replace("{name}", reference.name), {
        description: t("agentRefGoneHint"),
      });
      return;
    }
    if (route.href) {
      gotoRecord(route.href(reference.id), route.event, reference.id);
      return;
    }
    // 素材:要知道它是图还是视频才决定灯箱怎么放,而胶囊上只有 id 和名字。
    const asset = found as Asset;
    if (asset.kind !== "image" && asset.kind !== "video") {
      // 音频、文档这类没有灯箱可放的,跳去素材库里定位它 —— 总比点了没反应强。
      window.location.hash = `#/media?asset=${encodeURIComponent(asset.id)}`;
      return;
    }
    openImagePreview({ src: assetFileUrl(asset.id), title: asset.name, video: asset.kind === "video" });
  };
}
