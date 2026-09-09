import React from "react";
import { FileText, Music } from "lucide-react";

import { assetFileUrl, assetThumbnailUrl, importAsset, type Asset } from "@/api/client";
import { useI18n } from "@/app/preferences";
import { useImagePreview, type ImagePreviewItem } from "@/components/app/image-preview";
import type { ComposerChip } from "@/components/agent/ComposerChips";
import { toast } from "sonner";

/**
 * 智能体输入框的附件:选文件 / 拖进来 / **直接粘贴**,三种入口一套逻辑。
 *
 * **为什么抽出来**:此前对话页和工作流助手各写了一份,而且两份不一样 —— 工作流那边能内联
 * 文本文件、对话页不能;对话页只认「选文件」、粘贴一张截图什么也不会发生。同一个输入框在
 * 两个地方能力不同,用户没有任何办法预期哪个能干什么。
 *
 * 分流规则(两边共用):
 * - **图片 / 视频 / 音频** → 导入素材库,气泡里渲染成缩略图,智能体用 analyze_asset 看。
 *   和飞书发来的图片落在同一个地方 —— 一个应用里只该有一条"媒体从外面进来"的路。
 * - **文本文件** → 内联成围栏上下文。脚本、字幕、配置就该被读进去,而不是变成一个素材 id。
 * - 其余(压缩包、PDF…)拒绝并说明,不静默丢掉。
 */

/** 内联文本的大小上限。再大应拆分或放到外部文件里按需读取,不能塞满一轮对话上下文。 */
const MAX_TEXT_BYTES = 200 * 1024;

const MEDIA_TYPE = /^(image|video|audio)\//;

/** 粘贴板里当成文本文件读的类型。text/plain 不在其中 —— 那是普通粘贴,交给输入框自己。 */
const TEXTUAL_FILE = /^(text\/|application\/(json|xml|x-yaml|yaml|javascript|typescript))/;

export interface TextAttachment {
  name: string;
  content: string;
}

export interface ComposerAttachments {
  media: Asset[];
  files: TextAttachment[];
  uploading: boolean;
  /** 有没有东西待发送。 */
  isEmpty: boolean;
  /** 选文件 / 拖放 / 粘贴都汇到这里。 */
  accept: (files: Iterable<File> | FileList | null) => Promise<void>;
  /** 贴到输入框上的粘贴处理器;剪贴板里没有文件时返回 false,让浏览器照常粘文字。 */
  onPaste: (event: React.ClipboardEvent) => boolean;
  removeMedia: (index: number) => void;
  removeFile: (index: number) => void;
  clear: () => void;
  /** 交给 ComposerChips 显示的一排小条 —— 和笔记引用拼在同一排里。 */
  chips: ComposerChip[];
}

export function useComposerAttachments(workspaceId: string): ComposerAttachments {
  const t = useI18n();
  const [media, setMedia] = React.useState<Asset[]>([]);
  const [files, setFiles] = React.useState<TextAttachment[]>([]);
  const [uploading, setUploading] = React.useState(false);

  const accept = React.useCallback(
    async (incoming: Iterable<File> | FileList | null) => {
      if (!incoming) return;
      const list = Array.from(incoming as Iterable<File>);
      if (!list.length) return;
      const added: TextAttachment[] = [];
      for (const file of list) {
        if (MEDIA_TYPE.test(file.type)) {
          setUploading(true);
          try {
            const asset = await importAsset({ workspaceId, file });
            setMedia((current) => [...current, asset]);
          } catch {
            toast.error(t("composerFileUnreadable").replace("{name}", file.name || t("composerPastedImage")));
          } finally {
            setUploading(false);
          }
          continue;
        }
        // 类型为空的当文本试读:从终端/编辑器拖出来的文件常常没有 MIME。
        if (file.type && !TEXTUAL_FILE.test(file.type)) {
          toast.error(t("composerFileUnsupported").replace("{name}", file.name));
          continue;
        }
        if (file.size > MAX_TEXT_BYTES) {
          toast.error(t("composerFileTooBig").replace("{name}", file.name));
          continue;
        }
        try {
          added.push({ name: file.name, content: await file.text() });
        } catch {
          toast.error(t("composerFileUnreadable").replace("{name}", file.name));
        }
      }
      if (added.length) setFiles((current) => [...current, ...added]);
    },
    [workspaceId, t],
  );

  const onPaste = React.useCallback(
    (event: React.ClipboardEvent) => {
      const items = Array.from(event.clipboardData?.files ?? []);
      if (!items.length) return false;
      // 截图粘贴进来的 File 没有名字(name 是空串)。给它一个,否则素材库里出现一排无名文件。
      const named = items.map((file) =>
        file.name ? file : new File([file], `pasted-${Date.now()}.${file.type.split("/")[1] || "png"}`, { type: file.type }),
      );
      event.preventDefault();
      void accept(named);
      return true;
    },
    [accept],
  );

  const removeMedia = React.useCallback((index: number) => setMedia((c) => c.filter((_, i) => i !== index)), []);
  const removeFile = React.useCallback((index: number) => setFiles((c) => c.filter((_, i) => i !== index)), []);

  const { openImagePreview } = useImagePreview();
  const chips = React.useMemo<ComposerChip[]>(() => {
    // 图和视频一起进画廊:点开任意一张都能左右翻,不必关掉再点下一张。
    const gallery: ImagePreviewItem[] = media
      .filter((asset) => asset.kind === "image" || asset.kind === "video")
      .map((asset) => ({ src: assetFileUrl(asset.id), title: asset.name, video: asset.kind === "video" }));
    return [
      ...media.map((asset, index) => ({
        id: asset.id,
        label: asset.name,
        // 音频没有画面,给个音符;图和视频都有缩略图(视频那张是封面帧)。
        thumbnail: asset.kind === "audio" ? undefined : assetThumbnailUrl(asset.id),
        icon: <Music size={11} />,
        onOpen:
          asset.kind === "audio"
            ? undefined
            : () =>
                openImagePreview({
                  src: assetFileUrl(asset.id),
                  title: asset.name,
                  video: asset.kind === "video",
                  gallery,
                }),
        onRemove: () => removeMedia(index),
      })),
      ...files.map((file, index) => ({
        id: `${file.name}-${index}`,
        label: file.name,
        icon: <FileText size={11} />,
        // 文本附件是**整段读进上下文**的,点开看到的就是发出去的那段字。
        text: { title: file.name, body: file.content },
        onRemove: () => removeFile(index),
      })),
    ];
  }, [media, files, openImagePreview, removeMedia, removeFile]);

  return {
    media,
    files,
    uploading,
    isEmpty: media.length === 0 && files.length === 0,
    accept,
    onPaste,
    removeMedia,
    removeFile,
    chips,
    clear: React.useCallback(() => {
      setMedia([]);
      setFiles([]);
    }, []),
  };
}

/** 文本附件 → 发给模型的围栏上下文。两边同一种拼法,气泡里也就长得一样。 */
export function textAttachmentBlock(files: TextAttachment[], label: string): string {
  return files.map((file) => `[${label} ${file.name}]\n\`\`\`\n${file.content}\n\`\`\``).join("\n\n");
}
