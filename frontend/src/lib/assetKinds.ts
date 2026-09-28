import type { MessageKey } from "@/app/messages";

/**
 * 素材的几种和导入时认哪些文件(ADR 0031)。
 *
 * 文档的扩展名和后端 `media/probe.DOCUMENT_EXTENSIONS` 是同一张表(backend/tests/test_document_assets.py 钉着):
 * 前端据它决定「选文件」对话框列什么、拖进来的哪些收;真正认种类的是后端。
 */
export const DOCUMENT_EXTENSIONS = [
  ".pdf", ".docx", ".doc", ".pptx", ".ppt", ".xlsx", ".xls", ".csv",
  ".md", ".markdown", ".txt", ".html", ".htm", ".epub",
] as const;

/** 选文件对话框的 accept:媒体按类型,文档按扩展名(docx、md 的类型在各系统上报得五花八门)。 */
export const IMPORT_ACCEPT = ["video/*", "audio/*", "image/*", ...DOCUMENT_EXTENSIONS].join(",");

/** 视频、图片、音频。能放上时间线、当生成参考的只有这几种。 */
export function isMediaFile(file: File): boolean {
  return /^(video|image|audio)\//.test(file.type);
}

export function isDocumentFile(file: File): boolean {
  const name = file.name.toLowerCase();
  return DOCUMENT_EXTENSIONS.some((ext) => name.endsWith(ext));
}

/** 能进素材库的:媒体和文档。别的(压缩包、安装包)直接忽略,不弹错。 */
export function isImportableFile(file: File): boolean {
  return isMediaFile(file) || isDocumentFile(file);
}

/** 这份素材有画面或声音(能上时间线、能当生成参考)。文档没有。 */
export function isMediaAsset(asset: { kind: string }): boolean {
  return asset.kind === "image" || asset.kind === "video" || asset.kind === "audio";
}

/** 种类在界面上叫什么。认不出的当视频说 —— 素材库里只有这四种。 */
export function assetKindKey(kind: string): MessageKey {
  return kind === "image" ? "kindImage" : kind === "audio" ? "kindAudio" : kind === "document" ? "kindDocument" : "kindVideo";
}

/** 文档那一行:格式、页数(解析过才有)、大小 —— 素材库的卡片和详情用同一句。 */
export function documentFacts(asset: { media_info: Record<string, unknown> }): string {
  const info = asset.media_info as { format?: string; pages?: number; size_bytes?: number };
  const size = info.size_bytes
    ? info.size_bytes >= 1024 * 1024 ? `${(info.size_bytes / 1024 / 1024).toFixed(1)}MB` : `${Math.max(1, Math.round(info.size_bytes / 1024))}KB`
    : "";
  return [String(info.format ?? "").toUpperCase(), info.pages ? `${info.pages}p` : "", size].filter(Boolean).join(" · ") || "—";
}
