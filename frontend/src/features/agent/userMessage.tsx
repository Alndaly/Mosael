import React from "react";
import type { JSONContent } from "@tiptap/react";

import { AssetInlinePreview } from "@/components/app/asset-preview";
import { documentText } from "@/features/agent/ChatComposer";
import { ReferenceDocument } from "@/features/agent/ReferenceDocument";
import { assetFileUrl, assetPreviewUrl } from "@/api/client";
import type { ImagePreviewItem } from "@/components/app/image-preview";

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

/** 同一聊天里的图片/视频按出现顺序组成一个 react-photo-view 列表。 */
export function chatMediaGallery(messages: readonly { role?: string; content: string }[]): ImagePreviewItem[] {
  const seen = new Set<string>();
  const gallery: ImagePreviewItem[] = [];
  for (const message of messages) {
    if (message.role !== "user") continue;
    for (const attachment of parseUserContent(message.content).attachments) {
      if (attachment.kind !== "image" && attachment.kind !== "video") continue;
      if (seen.has(attachment.assetId)) continue;
      seen.add(attachment.assetId);
      gallery.push({
        src: attachment.kind === "image" ? assetPreviewUrl(attachment.assetId) : assetFileUrl(attachment.assetId),
        title: attachment.name,
        ...(attachment.kind === "video" ? { video: true } : {}),
      });
    }
  }
  return gallery;
}

/**
 * 用户消息的正文。
 *
 * **优先照编辑器文档渲染**:`@` 出来的引用在库里是原子节点(payload.body_document),
 * 照它画回来才是胶囊。只按 content 渲染的话,发送这个动作本身会把用户刚放进去的结构
 * 抹平成一串 `@名字` —— 而那正是这次要修的毛病。
 *
 * 没有文档就走老路(纯文本 + 附件标记):**老消息还得能看**,而它们只有 content。
 *
 * **文档只覆盖用户敲的那一段。** 发出去的 content 后面还接着别的:笔记引用的 `@标题`、
 * 文本附件内联成的围栏块 —— 它们是发送时拼上去的,不在编辑器里。只画文档的话,挂了三条
 * 笔记发出去,气泡里一点痕迹都没有。所以文档之后把 content 剩下的那截接着画出来。
 */
export function UserMessageContent({
  content,
  document,
  mediaGallery,
}: {
  content: string;
  document?: JSONContent | null;
  mediaGallery?: ImagePreviewItem[];
}) {
  const { text, attachments } = React.useMemo(() => parseUserContent(content), [content]);
  //: 文档画的是用户敲的那一段,它是 content 的**前缀**(拼接顺序见 ChatWorkspace.submit)。
  //: 对不上前缀时宁可不画尾巴,也不要把同一句话画两遍。
  const trailing = React.useMemo(() => {
    if (!document) return "";
    const head = documentText(document).trim();
    return text.startsWith(head) ? text.slice(head.length).trim() : "";
  }, [document, text]);
  if (document) {
    return (
      <div className="grid gap-1.5">
        <ReferenceDocument document={document} />
        {trailing && <div className="whitespace-pre-wrap">{trailing}</div>}
        {attachments.length > 0 && (
          <div className="flex flex-wrap gap-1.5">
            {attachments.map((att) => (
              <AssetInlinePreview
                key={att.assetId}
                assetId={att.assetId}
                name={att.name}
                kind={att.kind}
                gallery={mediaGallery}
              />
            ))}
          </div>
        )}
      </div>
    );
  }
  if (attachments.length === 0) return <div>{content}</div>;
  return (
    <div className="grid gap-1.5">
      {text && <div className="whitespace-pre-wrap">{text}</div>}
      <div className="flex flex-wrap gap-1.5">
        {attachments.map((att) => (
          <AssetInlinePreview
            key={att.assetId}
            assetId={att.assetId}
            name={att.name}
            kind={att.kind}
            gallery={mediaGallery}
          />
        ))}
      </div>
    </div>
  );
}
