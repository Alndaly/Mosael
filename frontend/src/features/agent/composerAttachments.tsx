import React from "react";
import { FileText, FileUp, Music } from "lucide-react";

import {
  assetThumbnailUrl,
  importAsset,
  unpackAgentBundleArchive,
  unpackAgentBundleFolder,
  type AgentBundle,
  type Asset,
} from "@/api/client";
import { errorText } from "@/api/errorMessage";
import type { MessageKey } from "@/app/messages";
import { useI18n } from "@/app/preferences";
import { assetGallery, assetPreviewItem } from "@/components/app/asset-preview";
import { useImagePreview } from "@/components/app/image-preview";
import { useAssetPreviewModal } from "@/features/media/AssetPreviewModalById";
import { ComposerBundleNotes, type BundleNote } from "@/features/agent/ComposerBundleNotes";
import type { ComposerChip } from "@/lib/composerChip";
import { folderTooLarge, MAX_FOLDER_BYTES, MAX_FOLDER_FILES, readDroppedFolder, type PickedFolder } from "@/lib/folderFiles";
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
 * - **Markdown、TXT、CSV、网页**:素材库认得的文字文档,和 PDF 一样进素材库(见 TEXT_DOCUMENT)。
 * - **别的文本文件**(脚本、字幕、配置)→ 内联成围栏上下文,一份最多 MAX_INLINE_CHARS 字 —— 它们就该被读进去,
 *   而不是变成一个素材 id;再长的装不进一条消息。
 * - **压缩包(.zip)和文件夹**(ADR 0059)→ 交给后端解开:里面有 SKILL.md 的是技能包,输入框上方出一张「发现 N 个技能,
 *   安装到工作区?」的卡,点开是设置页同一个导入审阅,确认了才装;不是技能包的,图片进素材库、文本文件合订成一份
 *   Markdown 文档进素材库(和附一份 .md 同一条路),其余的逐个列在卡上说没收。
 * - 其余(安装包、磁盘映像…)拒绝并说明,不静默丢掉。
 *
 * 三种入口只是「文件从哪来」不同,之后**同一个 accept**:同样的分流、同样的大小上限、同样的报错。
 * 拖放和粘贴另写一套的话,📎 能附上的文件拖进来可能被拒,或者反过来。
 */

/**
 * 一条消息最多多少字(后端 AgentMessageCreate:正文 `content` 8000、附带上下文 `context` 4000)。内联的文本附件就拼在
 * 这里面 —— 此前内联上限是 200KB,远大于一条消息装得下的,于是附件条上好好的,一发送就被拒「at most 8000 characters」
 * (用户截图:一份 70KB 的 Markdown)。
 */
export const MAX_MESSAGE_CHARS = 8000;
export const MAX_CONTEXT_CHARS = 4000;
/** 一份内联文本最多多少字:两个输入框都装得下(工作流助手把它放在 `context` 里),还给正文留出地方。 */
const MAX_INLINE_CHARS = 3000;

const MEDIA_TYPE = /^(image|video|audio)\//;

/** 读不成文字的文档:进素材库、解析之后给智能体读(纯文本类的 md / txt / csv 照旧内联)。 */
const BINARY_DOCUMENT = /\.(pdf|docx?|pptx?|xlsx?|epub)$/i;

/**
 * 素材库也认得的**文字文档**(后端 media/probe 的 DOCUMENT_EXTENSIONS):和 PDF 一样进素材库当文档 —— 后端解析成按段的
 * 全文,短的整篇放进上下文、长的给目录,智能体用 read_document 一段段读,没有一条消息装不装得下的问题。此前它们被内联进
 * 消息:大一点的附不上(「太大了」),小于内联上限却大于一条消息的附上了也发不出去。
 */
const TEXT_DOCUMENT = /\.(md|markdown|txt|csv|html?)$/i;

/** 交给后端解开的压缩包。只认 zip:技能导入也只认它,别的格式(rar、7z)浏览器和后端都没有现成的解法。 */
const ARCHIVE = /\.zip$/i;

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
  /** 选的 / 拖进来的文件夹(见 lib/folderFiles)。 */
  acceptFolder: (folder: PickedFolder | null) => Promise<void>;
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
  /** 换一处地方时,把那一处先前挂着的附件放回来(见 CanvasAgentChat:输入框里的东西按地方分,ADR 0044)。 */
  restore: (saved: { media: Asset[]; files: TextAttachment[] }) => void;
  /** 交给 ComposerChips 显示的一排小条 —— 和笔记引用拼在同一排里。 */
  chips: ComposerChip[];
  /** 点开音频、文档附件时的素材详情弹窗。调用方把它挂进树里(和输入框同一层)。 */
  previewModal: React.ReactNode;
  /** 压缩包 / 文件夹解开后要人看一眼的:发现了技能(装不装)、有文件没收(是哪些)。调用方摆在附件条上面。 */
  bundleNotes: React.ReactNode;
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
  const [notes, setNotes] = React.useState<BundleNote[]>([]);

  /** 交给后端解开一个压缩包 / 文件夹:进了素材库的放进附件条,要人看的(技能、没收的文件)放进卡里。 */
  const unpack = React.useCallback(
    async (name: string, run: () => Promise<AgentBundle>) => {
      setUploading(true);
      try {
        const bundle = await run();
        if (bundle.assets.length) setMedia((current) => [...current, ...bundle.assets]);
        if (bundle.skill_import || bundle.skipped.length) {
          setNotes((current) => [
            ...current,
            { id: `${name}-${Date.now()}`, sourceName: bundle.source_name || name, skillImport: bundle.skill_import ?? null, skipped: bundle.skipped },
          ]);
        }
      } catch (error) {
        toast.error(t("composerFileUnreadable").replace("{name}", name).replace("{reason}", readFailure(error, t)));
      } finally {
        setUploading(false);
      }
    },
    [t],
  );

  const acceptFolder = React.useCallback(
    async (folder: PickedFolder | null) => {
      if (!folder) return;
      if (!folder.files.length) {
        toast.error(t("composerFolderEmpty").replace("{name}", folder.name));
        return;
      }
      //: 先在这里挡:传完 20MB 才被后端拒,等于让人白等。
      if (folderTooLarge(folder)) {
        toast.error(
          t("composerFolderTooLarge")
            .replace("{name}", folder.name)
            .replace("{mb}", String(MAX_FOLDER_BYTES / (1024 * 1024)))
            .replace("{n}", String(MAX_FOLDER_FILES)),
        );
        return;
      }
      await unpack(folder.name, () => unpackAgentBundleFolder(workspaceId, folder.name, folder.files));
    },
    [workspaceId, unpack, t],
  );

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
        if (ARCHIVE.test(file.name)) {
          await unpack(file.name, () => unpackAgentBundleArchive(workspaceId, file));
          continue;
        }
        if (MEDIA_TYPE.test(file.type) || BINARY_DOCUMENT.test(file.name) || TEXT_DOCUMENT.test(file.name)) {
          await importFile(file);
          continue;
        }
        // 类型为空的当文本试读:从终端/编辑器拖出来的文件常常没有 MIME。
        if (file.type && !TEXTUAL_FILE.test(file.type)) {
          toast.error(t("composerFileUnsupported").replace("{name}", file.name));
          continue;
        }
        let content: string;
        try {
          content = await file.text();
        } catch (error) {
          toast.error(unreadable(file.name, error));
          continue;
        }
        if (content.length > MAX_INLINE_CHARS) {
          toast.error(t("composerFileTooBig").replace("{name}", file.name).replace("{limit}", String(MAX_INLINE_CHARS)));
          continue;
        }
        added.push({ name: file.name, content });
      }
      if (added.length) setFiles((current) => [...current, ...added]);
    },
    [workspaceId, unpack, t],
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
  //: 拖进来的文件夹单独交过来(不传的话它混在文件里,是一个读不出内容的空壳)。一个一个读、一个一个解开。
  const fileDrop = useFileDrop(
    (dropped) => void accept(dropped),
    undefined,
    undefined,
    (folders) => {
      void (async () => {
        for (const entry of folders) {
          try {
            await acceptFolder(await readDroppedFolder(entry));
          } catch (error) {
            toast.error(t("composerFileUnreadable").replace("{name}", entry.name).replace("{reason}", readFailure(error, t)));
          }
        }
      })();
    },
  );
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
    // 图和视频一起进画廊:点开任意一张都能左右翻,不必关掉再点下一张。图走预览地址(HEIC 原图浏览器解不了)。
    const gallery = assetGallery(media);
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
            : () => {
                const item = assetPreviewItem(asset);
                if (item) openImagePreview({ ...item, gallery });
              },
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
    acceptFolder,
    bundleNotes: (
      <ComposerBundleNotes
        workspaceId={workspaceId}
        notes={notes}
        onDismiss={(id) => setNotes((current) => current.filter((note) => note.id !== id))}
      />
    ),
    //: 「没收的文件」说的是这一条消息带了什么,发出去 / 换一处就收起;「发现技能」的卡留着,直到装了或点忽略 ——
    //: 先说一句「装好后帮我…」再去装是常有的事,卡跟着消息一起消失的话就再也找不到这次暂存了。
    clear: React.useCallback(() => {
      setMedia([]);
      setFiles([]);
      setNotes((current) => current.filter((note) => note.skillImport));
    }, []),
    restore: React.useCallback((saved: { media: Asset[]; files: TextAttachment[] }) => {
      setMedia(saved.media);
      setFiles(saved.files);
      setNotes((current) => current.filter((note) => note.skillImport));
    }, []),
  };
}

/** 文本附件 → 发给模型的围栏上下文。两边同一种拼法,气泡里也就长得一样。 */
export function textAttachmentBlock(files: TextAttachment[], label: string): string {
  return files.map((file) => `[${label} ${file.name}]\n\`\`\`\n${file.content}\n\`\`\``).join("\n\n");
}
