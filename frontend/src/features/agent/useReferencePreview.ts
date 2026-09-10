import { assetFileUrl, type Asset } from "@/api/client";
import { api } from "@/api/transport";
import { useImagePreview } from "@/components/app/image-preview";
import { noteHref } from "@/api/domains/notes";
import type { AgentReference } from "@/features/agent/references";

/**
 * 点开一个引用。
 *
 * 引用胶囊在输入框里和气泡里长得一样,**点开的行为也该一样** —— 用户刚亲手把它放进去,
 * 发出去之后点它却什么都不发生,那读起来像是发送把它变成了一张死图。
 *
 * 各类各有各的"打开"是本来如此,不是特例:
 * - 素材有画面 → 全局灯箱(那里已经有翻页、Esc 和层级,不必再造一个)
 * - 笔记、画板、工作流是**页面** → 跳过去。塞进一个小弹层里只能看个开头,
 *   而它们本来就有自己的完整界面。
 */
export function useReferencePreview() {
  const { openImagePreview } = useImagePreview();
  return async (reference: AgentReference) => {
    if (reference.kind === "note") {
      window.location.hash = noteHref(reference.id);
      return;
    }
    if (reference.kind === "board") {
      window.location.hash = `#/boards?board=${encodeURIComponent(reference.id)}`;
      return;
    }
    if (reference.kind === "workflow") {
      window.location.hash = `#/workflows?workflow=${encodeURIComponent(reference.id)}`;
      return;
    }
    // 素材:要知道它是图还是视频才决定灯箱怎么放,而胶囊上只有 id 和名字。
    const asset = await api<Asset>(`/api/assets/${reference.id}`).catch(() => null);
    if (!asset) return;
    if (asset.kind !== "image" && asset.kind !== "video") return;
    openImagePreview({ src: assetFileUrl(asset.id), title: asset.name, video: asset.kind === "video" });
  };
}
