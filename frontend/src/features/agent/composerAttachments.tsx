import React from "react";
import { FileText, FileUp, Music } from "lucide-react";

import { assetFileUrl, assetThumbnailUrl, importAsset, type Asset } from "@/api/client";
import { errorText } from "@/api/errorMessage";
import type { MessageKey } from "@/app/messages";
import { useI18n } from "@/app/preferences";
import { useImagePreview, type ImagePreviewItem } from "@/components/app/image-preview";
import { useAssetPreviewModal } from "@/features/media/AssetPreviewModalById";
import type { ComposerChip } from "@/lib/composerChip";
import { useFileDrop, type FileDrop } from "@/lib/useFileDrop";
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
 * - **PDF / Word / PPT / Excel / EPUB**(ADR 0031)→ 也进素材库(导入时自动解析),作为附件发过去:短的全文、
 *   长的目录由后端放进上下文,智能体用 read_document 按段读、analyze_document_pages 看版式。
 * - **文本文件**(含 Markdown、CSV)→ 内联成围栏上下文。脚本、字幕、配置就该被读进去,而不是变成一个素材 id。
 *   其中素材库也认得的文字文档(md / txt / csv / html)超过内联上限、或读不出来时,进素材库当文档(见 TEXT_DOCUMENT)。
 * - 其余(压缩包、安装包…)拒绝并说明,不静默丢掉。
 *
 * 三种入口只是「文件从哪来」不同,之后**同一个 accept**:同样的分流、同样的大小上限、同样的报错。
 * 拖放和粘贴另写一套的话,📎 能附上的文件拖进来可能被拒,或者反过来。
 */

/** 内联文本的大小上限。再大应拆分或放到外部文件里按需读取,不能塞满一轮对话上下文。 */
const MAX_TEXT_BYTES = 200 * 1024;

const MEDIA_TYPE = /^(image|video|audio)\//;

/** 读不成文字的文档:进素材库、解析之后给智能体读(纯文本类的 md / txt / csv 照旧内联)。 */
const BINARY_DOCUMENT = /\.(pdf|docx?|pptx?|xlsx?|epub)$/i;

/**
 * 素材库也认得的**文字文档**(后端 media/probe 的 DOCUMENT_EXTENSIONS):短的照旧内联;超过内联上限、或者这里读不出来时,
 * 进素材库当文档 —— 后端解析成按段的全文,智能体用 read_document 一段段读。此前一律「太大了」「读不出来」,一份几百 KB
 * 的整理稿(用户截图:「赛里木湖纪录片全案_整理版.md」读不出来)就附不上。
 */
const TEXT_DOCUMENT = /\.(md|markdown|txt|csv|html?)$/i;

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
  /**
   * 从访达 / 桌面把文件拖进来。`handlers` 摊到**整块对话区**上(不只是输入框 —— 输入框只有两行高,
   * 瞄准它松手太难),`overlay` 挂在同一块里,那块要是定位容器(relative / fixed)。
   * 只认真带文件的拖拽(见 useFileDrop):拖选一段字、编辑器里挪一个引用胶囊都不会亮提示。
   */
  drop: { handlers: FileDrop["handlers"]; overlay: React.ReactNode };
  removeMedia: (index: number) => void;
  removeFile: (index: number) => void;
  clear: () => void;
  /** 交给 ComposerChips 显示的一排小条 —— 和笔记引用拼在同一排里。 */
  chips: ComposerChip[];
  /** 点开音频、文档附件时的素材详情弹窗。调用方把它挂进树里(和输入框同一层)。 */
  previewModal: React.ReactNode;
}

/** 这个文件现在读得出来吗(读一个字节)。 */
async function readable(file: File): Promise<boolean> {
  try {
    await file.slice(0, 1).arrayBuffer();
    return true;
  } catch {
    return false;
  }
}

/** 为什么没附上:接口的报错照原话;浏览器读文件失败(NotReadableError)说人话 —— 多半是云盘里还没下载下来的占位文件,
 *  或者正被别的程序写着。 */
function readFailure(error: unknown, t: (key: MessageKey) => string): string {
  if (error instanceof DOMException && (error.name === "NotReadableError" || error.name === "NotFoundError")) {
    return t("composerFileNotReadable");
  }
  return errorText(error);
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
      /** 进素材库。失败时报出是哪一个、**为什么**(只说「读不出来」等于没说)。 */
      const importFile = async (file: File) => {
        setUploading(true);
        try {
          const asset = await importAsset({ workspaceId, file });
          setMedia((current) => [...current, asset]);
        } catch (error) {
          //: 上传失败时先看是不是**文件本身读不出来**:系统不让读的文件(别的应用沙盒里的、云盘占位),上传那一步的
          //: fetch 只会抛一个网络错误,原样说出来就成了「127.0.0.1:8800 连不上」—— 后端明明好好的(用户截图)。
          const cause = (await readable(file)) ? error : new DOMException("", "NotReadableError");
          toast.error(unreadable(file.name || t("composerPastedImage"), cause));
        } finally {
          setUploading(false);
        }
      };
      const unreadable = (name: string, error: unknown) =>
        t("composerFileUnreadable").replace("{name}", name).replace("{reason}", readFailure(error, t));
      for (const file of list) {
        if (MEDIA_TYPE.test(file.type) || BINARY_DOCUMENT.test(file.name)) {
          await importFile(file);
          continue;
        }
        const document = TEXT_DOCUMENT.test(file.name);
        // 类型为空的当文本试读:从终端/编辑器拖出来的文件常常没有 MIME。
        if (file.type && !TEXTUAL_FILE.test(file.type) && !document) {
          toast.error(t("composerFileUnsupported").replace("{name}", file.name));
          continue;
        }
        if (file.size > MAX_TEXT_BYTES) {
          if (document) await importFile(file);
          else toast.error(t("composerFileTooBig").replace("{name}", file.name));
          continue;
        }
        let content: string;
        try {
          content = await file.text();
        } catch (error) {
          //: 这里读不出来(云盘占位文件、正被别的程序写着)时,文字文档再交给素材库试一次:上传走的是另一条读法,
          //: 读得到就当文档附上;还不行才报,报的是上传那一次的原因。
          if (document) await importFile(file);
          else toast.error(unreadable(file.name, error));
          continue;
        }
        added.push({ name: file.name, content });
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

  //: 不在这里按类型筛:收不了的文件也交给 accept,由它报出是哪一个、为什么 —— 和 📎 选到同一个文件时一样。
  //: 在这里筛掉的话,拖进一个压缩包松手后什么都不发生,用户不知道是没拖中还是不支持。
  const fileDrop = useFileDrop((dropped) => void accept(dropped));
  //: inset-0 一点不留、盖过输入卡和消息:落点是整块对话区,不是某个方框(素材库、工作流画布同款)。
  const dropOverlay = fileDrop.active ? (
    <div className="pointer-events-none absolute inset-0 z-40 grid place-items-center bg-[color-mix(in_oklab,var(--primary)_10%,var(--background))]">
      <span className="grid justify-items-center gap-2 rounded-lg border-2 border-dashed border-primary px-6 py-4 text-ui-md font-semibold text-primary">
        <FileUp size={20} />
        {t("composerDropHint")}
      </span>
    </div>
  ) : null;

  const removeMedia = React.useCallback((index: number) => setMedia((c) => c.filter((_, i) => i !== index)), []);
  const removeFile = React.useCallback((index: number) => setFiles((c) => c.filter((_, i) => i !== index)), []);

  const { openImagePreview } = useImagePreview();
  const { openAsset, modal: assetModal } = useAssetPreviewModal();
  const chips = React.useMemo<ComposerChip[]>(() => {
    // 图和视频一起进画廊:点开任意一张都能左右翻,不必关掉再点下一张。
    const gallery: ImagePreviewItem[] = media
      .filter((asset) => asset.kind === "image" || asset.kind === "video")
      .map((asset) => ({ src: assetFileUrl(asset.id), title: asset.name, video: asset.kind === "video" }));
    return [
      ...media.map((asset, index) => ({
        id: asset.id,
        label: asset.name,
        // 音频没有画面,给个音符;文档给个文件图标(封面要等解析完);图和视频都有缩略图(视频那张是封面帧)。
        thumbnail: asset.kind === "audio" || asset.kind === "document" ? undefined : assetThumbnailUrl(asset.id),
        icon: asset.kind === "document" ? <FileText size={11} /> : <Music size={11} />,
        //: 音频、文档没有灯箱可放:点开是素材详情(文档是三栏阅读),不是点了没反应。
        onOpen:
          asset.kind === "audio" || asset.kind === "document"
            ? () => openAsset(asset.id)
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
  }, [media, files, openImagePreview, openAsset, removeMedia, removeFile]);

  return {
    media,
    files,
    uploading,
    isEmpty: media.length === 0 && files.length === 0,
    accept,
    onPaste,
    drop: { handlers: fileDrop.handlers, overlay: dropOverlay },
    removeMedia,
    removeFile,
    chips,
    previewModal: assetModal,
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
