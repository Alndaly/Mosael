import { withSlotProducer, type Asset, type BoardItem } from "@/api/client";
import type { DocumentText } from "@/api/domains/documents";
import type { NoteReference } from "@/api/domains/notes";
import { isImportableFile } from "@/lib/useFileDrop";

import { BOARD_TEXT_MAX, DEFAULT_SIZE, isMediaKind, type MediaKind } from "./boardNodes";

/** 进了素材库、要摆上画板的一份素材:媒体各落成同名的格子,文档(ADR 0031)落成一格文档格。 */
export interface PlacedAsset {
  id: string;
  name: string;
  kind: MediaKind | "document";
}

/**
 * 素材库里的一份素材 → 要摆上画板的样子。拖进来 / 粘贴进来的文件和「添加 → 素材」从库里挑的都走这里,
 * 两条路上格子的名字取法和「哪些种类放得上画板」是同一个判据。画板上没有那种格子(文本、字幕……)回 null:
 * 它只进素材库、不上画板。名字空着(没起名的导入)退回原始文件名。
 */
export function placedAsset(asset: Pick<Asset, "id" | "name" | "original_filename" | "kind">): PlacedAsset | null {
  if (!isMediaKind(asset.kind) && asset.kind !== "document") return null;
  return { id: asset.id, name: asset.name || asset.original_filename || "", kind: asset.kind };
}

/** 文档素材解析出的全文 → 和笔记引用同一个样子,连进写作 / 生成格的那一侧不必分它是哪一种。 */
export function assetReference(text: DocumentText): NoteReference {
  return { note_id: "", revision: 0, title: text.title, markdown: text.markdown, tags: [], citation_url: "" };
}

/**
 * 一格放着这份素材时写进去的字段:指向哪一份、叫什么。拖进来 / 粘贴进来(assetItem)和「添加 → 素材」
 * (从素材库挑,见 BoardsView)写的是同一份 —— 此前后者只写 asset_id,同一份素材两种放法格子上的名字不一样。
 */
export function assetFields(asset: PlacedAsset): Pick<BoardItem, "asset_id" | "text"> {
  return { asset_id: asset.id, text: asset.name };
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
    ...assetFields(asset),
  });
}


/**
 * 粘贴板上有什么可以落到画板上:媒体文件(截图、从访达复制的图/视频/音频)→ 先进素材库再各放一格;
 * 否则纯文字 → 一张便签。**文件优先** —— 从浏览器复制一张图,粘贴板上常常同时带着图和一段 HTML / 链接,
 * 用户要的是那张图。什么都没有(或只有空白)回 null,交给默认行为。
 */
export function clipboardContent(data: Pick<DataTransfer, "files" | "getData"> | null): { files: File[] } | { text: string } | null {
  if (!data) return null;
  const files = Array.from(data.files ?? [])
    .filter(isImportableFile)
    // 截图粘贴进来的 File 没有名字(name 是空串)。给它一个,否则素材库里出现一排无名文件。
    .map((file) =>
      file.name ? file : new File([file], `pasted-${Date.now()}.${file.type.split("/")[1] || "png"}`, { type: file.type }),
    );
  if (files.length) return { files };
  const text = data.getData("text/plain").trim();
  return text ? { text: text.slice(0, BOARD_TEXT_MAX) } : null;
}
