import React from "react";
import { Node, NodeViewWrapper, ReactNodeViewRenderer, mergeAttributes, type JSONContent } from "@tiptap/react";
import StarterKit from "@tiptap/starter-kit";
import type { CollaborationComment, WorkspaceMember } from "@/api/client";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";

export const CommentMembers = React.createContext<WorkspaceMember[]>([]);

function Mention({ userId, label }: { userId: string; label: string }) {
  const member = React.useContext(CommentMembers).find(one => one.user_id === userId);
  return <Popover>
    <PopoverTrigger asChild>
      <button type="button" data-user-mention="" data-user-id={userId}
        className="inline-flex cursor-pointer rounded-md bg-primary/15 px-1 py-0.5 text-primary hover:bg-primary/25 focus-visible:outline focus-visible:outline-2 focus-visible:outline-ring">
        @{label}
      </button>
    </PopoverTrigger>
    <PopoverContent data-board-comment-overlay="" align="start" className="w-56 p-3" onPointerDown={event => event.stopPropagation()} onClick={event => event.stopPropagation()}>
      <div className="flex items-center gap-2.5">
        <span className="grid size-8 shrink-0 place-items-center rounded-full bg-primary/15 text-ui-xs font-semibold text-primary">{(member?.display_name || label).slice(0, 1).toUpperCase()}</span>
        <div className="min-w-0 text-ui-xs"><p className="truncate font-medium">{member?.display_name || label}</p>{member && <p className="truncate text-muted-foreground">@{member.username}</p>}</div>
      </div>
    </PopoverContent>
  </Popover>;
}

export const UserMention = Node.create({
  name: "userMention", group: "inline", inline: true, atom: true, selectable: true,
  addAttributes: () => ({ userId: { default: "" }, label: { default: "" } }),
  parseHTML: () => [{ tag: "span[data-user-mention]" }],
  renderHTML: ({ HTMLAttributes }) => ["span", mergeAttributes(HTMLAttributes, { "data-user-mention": "" }), `@${String(HTMLAttributes.label ?? "")}`],
  renderText: ({ node }) => `@${String(node.attrs.label ?? "")}`,
  addNodeView: () => ReactNodeViewRenderer(({ node }) => <NodeViewWrapper as="span" contentEditable={false}>
    <Mention userId={String(node.attrs.userId ?? "")} label={String(node.attrs.label ?? "")} />
  </NodeViewWrapper>),
});

export function commentExtensions() {
  return [UserMention, StarterKit.configure({ heading: false, bulletList: false, orderedList: false,
    listItem: false, blockquote: false, codeBlock: false, horizontalRule: false,
    link: { openOnClick: false } })];
}

/** Plain legacy comments are text, never HTML passed into the editor. */
export function commentDocument(comment: Pick<CollaborationComment, "body" | "body_document">): JSONContent {
  if (comment.body_document?.type === "doc" && Array.isArray(comment.body_document.content)) return comment.body_document;
  return { type: "doc", content: comment.body.split("\n").map(text => ({ type: "paragraph", content: text ? [{ type: "text", text }] : [] })) };
}

export const COMMENT_TEXT = "text-ui-sm leading-relaxed text-foreground whitespace-pre-wrap break-words [&_p]:m-0 [&_p+p]:mt-1 [&_code]:rounded [&_code]:bg-secondary [&_code]:px-1";
