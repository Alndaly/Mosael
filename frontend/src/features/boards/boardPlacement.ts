import { withSlotProducer, type BoardItem } from "@/api/client";
import { isMediaFile } from "@/lib/useFileDrop";

import { DEFAULT_SIZE, type MediaKind } from "./boardNodes";

/** 进了素材库、要摆上画板的一份素材。 */
export interface PlacedAsset {
  id: string;
  name: string;
  kind: MediaKind;
}

/**
 * 一份素材 → 画板上放它的那一格。**素材上画板只走这一处**(拖进来的文件、粘贴进来的截图):图片、视频、
 * 音频各落成同名的格子 —— 服务端也按这张对照表收(canvas._ASSET_KIND_OF_ITEM),种类对不上存不下。
 *
 * 几份一起放时斜着摞开(`index`),不然它们会精确重叠成一个。
 */
export function assetItem(asset: PlacedAsset, at: { x: number; y: number }, index = 0): BoardItem {
  return withSlotProducer({
    id: `${asset.kind}-${Math.random().toString(36).slice(2, 9)}`,
    kind: asset.kind,
    x: Math.round(at.x + index * 24),
    y: Math.round(at.y + index * 24),
    ...DEFAULT_SIZE[asset.kind],
    asset_id: asset.id,
    text: asset.name,
  });
}

/** 便签正文的上限(后端 canvas.MAX_TEXT_CHARS)。粘进来的一大段超了的话,整张板存不下。 */
const NOTE_TEXT_LIMIT = 20_000;

/**
 * 粘贴板上有什么可以落到画板上:媒体文件(截图、从访达复制的图/视频/音频)→ 先进素材库再各放一格;
 * 否则纯文字 → 一张便签。**文件优先** —— 从浏览器复制一张图,粘贴板上常常同时带着图和一段 HTML / 链接,
 * 用户要的是那张图。什么都没有(或只有空白)回 null,交给默认行为。
 */
export function clipboardContent(data: Pick<DataTransfer, "files" | "getData"> | null): { files: File[] } | { text: string } | null {
  if (!data) return null;
  const files = Array.from(data.files ?? [])
    .filter(isMediaFile)
    // 截图粘贴进来的 File 没有名字(name 是空串)。给它一个,否则素材库里出现一排无名文件。
    .map((file) =>
      file.name ? file : new File([file], `pasted-${Date.now()}.${file.type.split("/")[1] || "png"}`, { type: file.type }),
    );
  if (files.length) return { files };
  const text = data.getData("text/plain").trim();
  return text ? { text: text.slice(0, NOTE_TEXT_LIMIT) } : null;
}
