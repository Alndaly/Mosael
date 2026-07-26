import React from "react";
import { Paperclip } from "lucide-react";

import { assetFileUrl } from "@/api/client";
import { useImagePreview } from "@/components/app/image-preview";

/**
 * 用户消息里「素材附件」的统一编码与渲染——AI Studio 对话页与工作流助手共用一套,避免两处漂移。
 *
 * 发送时素材被拼成 `[附件 asset_id=… 名称=… 类型=…]` 交给智能体识别;用户气泡里再从正文里拆出来,
 * 渲染成缩略图/文件胶囊,而不是把这段标记原样显示。名称可含空格,所以非贪婪匹配到 “ 类型=”。
 */
const ATTACHMENT_TOKEN = /\n?\[附件 asset_id=(\S+) 名称=(.*?) 类型=([a-z]+)\]/g;

/** 把一个素材编码成消息正文里的附件标记(与 parseUserContent 对应)。 */
export function attachmentToken(asset: { id: string; name: string; kind: string }): string {
  return `\n[附件 asset_id=${asset.id} 名称=${asset.name} 类型=${asset.kind}]`;
}

export function parseUserContent(content: string): {
  text: string;
  attachments: { assetId: string; name: string; kind: string }[];
} {
  const attachments: { assetId: string; name: string; kind: string }[] = [];
  const text = content
    .replace(ATTACHMENT_TOKEN, (_match, assetId: string, name: string, kind: string) => {
      attachments.push({ assetId, name, kind });
      return "";
    })
    .trim();
  return { text, attachments };
}

function UserAttachment({ assetId, name, kind }: { assetId: string; name: string; kind: string }) {
  const { openImagePreview } = useImagePreview();
  const src = assetFileUrl(assetId);
  if (kind === "image") {
    return (
      <button
        type="button"
        title={name}
        className="block max-h-[180px] w-fit max-w-full cursor-zoom-in overflow-hidden rounded-lg border border-border bg-black p-0"
        onClick={() => openImagePreview({ src, title: name })}
      >
        <img src={src} alt={name} loading="lazy" className="block max-h-[180px] w-auto max-w-full object-contain" />
      </button>
    );
  }
  if (kind === "video") {
    return <video src={src} controls preload="metadata" className="max-h-[200px] max-w-full rounded-lg border border-border bg-black" />;
  }
  if (kind === "audio") {
    return <audio src={src} controls preload="metadata" className="w-[260px] max-w-full" />;
  }
  return (
    <span className="inline-flex max-w-full items-center gap-[5px] rounded-lg border border-border bg-panel px-2 py-1 text-[11.5px] text-muted-foreground">
      <Paperclip size={12} className="shrink-0" />
      <span className="truncate" title={name}>{name}</span>
    </span>
  );
}

export function UserMessageContent({ content }: { content: string }) {
  const { text, attachments } = React.useMemo(() => parseUserContent(content), [content]);
  if (attachments.length === 0) return <div>{content}</div>;
  return (
    <div className="grid gap-1.5">
      {text && <div className="whitespace-pre-wrap">{text}</div>}
      <div className="flex flex-wrap gap-1.5">
        {attachments.map((att) => (
          <UserAttachment key={att.assetId} assetId={att.assetId} name={att.name} kind={att.kind} />
        ))}
      </div>
    </div>
  );
}
