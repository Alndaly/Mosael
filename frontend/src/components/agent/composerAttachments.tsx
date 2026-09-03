import React from "react";
import { Paperclip, X } from "lucide-react";

import { importAsset, type Asset } from "@/api/client";
import { useI18n } from "@/app/preferences";
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

  return {
    media,
    files,
    uploading,
    isEmpty: media.length === 0 && files.length === 0,
    accept,
    onPaste,
    removeMedia: React.useCallback((index) => setMedia((c) => c.filter((_, i) => i !== index)), []),
    removeFile: React.useCallback((index) => setFiles((c) => c.filter((_, i) => i !== index)), []),
    clear: React.useCallback(() => {
      setMedia([]);
      setFiles([]);
    }, []),
  };
}

/** 输入框上方那排附件小条。两个输入框共用,免得同一个东西长两个样。 */
export function AttachmentChips({ attachments, className }: { attachments: ComposerAttachments; className?: string }) {
  const t = useI18n();
  const { media, files, uploading, removeMedia, removeFile } = attachments;
  if (!media.length && !files.length && !uploading) return null;
  return (
    <div className={className ?? "flex flex-wrap gap-1 px-3.5 pt-1"}>
      {media.map((asset, index) => (
        <Chip key={asset.id} label={asset.name} onRemove={() => removeMedia(index)} />
      ))}
      {files.map((file, index) => (
        <Chip key={`${file.name}-${index}`} label={file.name} onRemove={() => removeFile(index)} />
      ))}
      {uploading && <span className="text-ui-xs text-muted-foreground">{t("composerUploading")}</span>}
    </div>
  );
}

function Chip({ label, onRemove }: { label: string; onRemove: () => void }) {
  const t = useI18n();
  return (
    <span
      className="inline-flex max-w-40 items-center gap-1 rounded-md border border-border bg-secondary py-0.5 pl-1.5 pr-1 text-ui-xs text-foreground"
      title={label}
    >
      <Paperclip size={11} className="shrink-0" />
      <span className="truncate">{label}</span>
      <button
        type="button"
        className="inline-flex cursor-pointer border-0 bg-transparent p-0 text-muted-foreground hover:text-foreground"
        aria-label={t("close")}
        onClick={onRemove}
      >
        <X size={11} />
      </button>
    </span>
  );
}

/** 文本附件 → 发给模型的围栏上下文。两边同一种拼法,气泡里也就长得一样。 */
export function textAttachmentBlock(files: TextAttachment[], label: string): string {
  return files.map((file) => `[${label} ${file.name}]\n\`\`\`\n${file.content}\n\`\`\``).join("\n\n");
}
