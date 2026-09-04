import React from "react";
import Placeholder from "@tiptap/extension-placeholder";
import {
  EditorContent,
  type JSONContent,
  Node,
  NodeViewWrapper,
  ReactNodeViewRenderer,
  mergeAttributes,
  useEditor,
} from "@tiptap/react";
import StarterKit from "@tiptap/starter-kit";
import { Send, X } from "lucide-react";

import type { WorkspaceMember } from "@/api/client";
import { useI18n } from "@/app/preferences";
import { RefSuggestion } from "@/components/app/refSuggestion";
import { useSuggestionMenu } from "@/components/app/suggestionMenu";
import { Button } from "@/components/ui/button";

export type CommentDocument = JSONContent;

export interface CommentDraft {
  body: string;
  bodyDocument: CommentDocument;
  mentionedUserIds: string[];
}

const UserMention = Node.create({
  name: "userMention",
  group: "inline",
  inline: true,
  atom: true,
  selectable: true,
  addAttributes: () => ({ userId: { default: "" }, label: { default: "" } }),
  parseHTML: () => [{ tag: "span[data-user-mention]" }],
  renderHTML: ({ HTMLAttributes }: { HTMLAttributes: Record<string, unknown> }) => [
    "span",
    mergeAttributes(HTMLAttributes, { "data-user-mention": "" }),
  ],
  renderText: ({ node }: { node: { attrs: Record<string, unknown> } }) => `@${String(node.attrs.label ?? "")}`,
  addNodeView: () =>
    ReactNodeViewRenderer(({ node }: { node: { attrs: Record<string, unknown> } }) => (
      <NodeViewWrapper
        as="span"
        data-user-mention=""
        data-user-id={String(node.attrs.userId ?? "")}
        className="inline-flex rounded-md bg-primary/15 px-1 py-0.5 text-primary"
      >
        @{String(node.attrs.label ?? "")}
      </NodeViewWrapper>
    )),
});

/** Extract immutable user IDs from the editor document; labels are presentation only. */
export function collectMentionedUserIds(document: CommentDocument | null): string[] {
  const found: string[] = [];
  const walk = (node: Record<string, unknown>) => {
    if (node.type === "userMention") {
      const userId = String((node.attrs as Record<string, unknown> | undefined)?.userId ?? "");
      if (userId && !found.includes(userId)) found.push(userId);
    }
    for (const child of (node.content as Record<string, unknown>[] | undefined) ?? []) walk(child);
  };
  if (document) walk(document as Record<string, unknown>);
  return found;
}

export function BoardCommentComposer({
  members,
  onSubmit,
  onCancel,
}: {
  members: WorkspaceMember[];
  onSubmit: (draft: CommentDraft) => Promise<unknown>;
  onCancel: () => void;
}) {
  const t = useI18n();
  const membersRef = React.useRef(members);
  membersRef.current = members;
  const [submitting, setSubmitting] = React.useState(false);
  const [empty, setEmpty] = React.useState(true);
  const menu = useSuggestionMenu<WorkspaceMember>({ emptyHint: () => t("commentMentionEmpty") });
  const submitRef = React.useRef<() => void>(() => undefined);

  const editor = useEditor({
    extensions: [
      UserMention,
      StarterKit.configure({
        heading: false,
        bulletList: false,
        orderedList: false,
        listItem: false,
        blockquote: false,
        codeBlock: false,
        horizontalRule: false,
      }),
      Placeholder.configure({ placeholder: t("commentCanvasPlaceholder") }),
      RefSuggestion.configure({
        suggestion: {
          char: "@",
          allowedPrefixes: null,
          items: ({ query }) => {
            const needle = query.trim().toLocaleLowerCase();
            return membersRef.current
              .filter((member) => member.username || member.display_name)
              .filter((member) => {
                if (!needle) return true;
                return `${member.display_name} ${member.username}`.toLocaleLowerCase().includes(needle);
              })
              .slice(0, 10);
          },
          command: ({ editor: instance, range, props }) => {
            const member = props as unknown as WorkspaceMember;
            instance
              .chain()
              .focus()
              .deleteRange(range)
              .insertContent([
                {
                  type: "userMention",
                  attrs: { userId: member.user_id, label: member.display_name || member.username },
                },
                { type: "text", text: " " },
              ])
              .run();
          },
          render: menu.render,
        },
      }),
    ],
    autofocus: "end",
    editorProps: {
      attributes: {
        class: "nodrag nopan min-h-20 w-full cursor-text px-3 py-2 text-ui-sm leading-relaxed text-foreground outline-none",
        "aria-label": t("commentCanvasPlaceholder"),
      },
      handleKeyDown: (_view, event) => {
        if (event.key === "Escape") {
          onCancel();
          return true;
        }
        if (event.key === "Enter" && (event.metaKey || event.ctrlKey)) {
          event.preventDefault();
          submitRef.current();
          return true;
        }
        return false;
      },
    },
    onUpdate: ({ editor: instance }) => setEmpty(!instance.getText().trim()),
  });

  const submit = React.useCallback(() => {
    if (!editor || !editor.getText().trim() || submitting) return;
    const bodyDocument = editor.getJSON() as CommentDocument;
    setSubmitting(true);
    void onSubmit({
      body: editor.getText({ blockSeparator: "\n" }).trim(),
      bodyDocument,
      mentionedUserIds: collectMentionedUserIds(bodyDocument),
    }).finally(() => setSubmitting(false));
  }, [editor, onSubmit, submitting]);
  submitRef.current = submit;

  return (
    <div
      className="nodrag nopan w-72 cursor-default overflow-hidden rounded-xl border border-border-strong bg-panel/95 shadow-[var(--shadow-panel)] backdrop-blur-xl"
      onPointerDown={(event) => event.stopPropagation()}
      onMouseDown={(event) => event.stopPropagation()}
      onClick={(event) => event.stopPropagation()}
      onDoubleClick={(event) => event.stopPropagation()}
    >
      <EditorContent editor={editor} />
      <div className="flex items-center justify-between border-t border-border px-2 py-1.5">
        <span className="text-ui-2xs text-muted-foreground">{t("commentMentionHint")}</span>
        <div className="flex items-center gap-1">
          <Button variant="ghost" size="icon" className="h-7 w-7" onClick={onCancel} aria-label={t("cancel")}>
            <X size={13} />
          </Button>
          <Button size="icon" className="h-7 w-7" disabled={empty} loading={submitting} onClick={submit} aria-label={t("send")}>
            <Send size={13} />
          </Button>
        </div>
      </div>
      <menu.Portal>
        {(member, index) => (
          <button
            key={member.user_id}
            type="button"
            className={`flex w-full items-center gap-2 rounded px-2 py-1.5 text-left text-ui-sm ${menu.menu?.active === index ? "bg-secondary text-foreground" : "text-muted-foreground hover:bg-secondary"}`}
            onMouseDown={(event) => event.preventDefault()}
            onClick={() => menu.choose(member)}
          >
            <span className="grid h-6 w-6 shrink-0 place-items-center rounded-full bg-secondary text-ui-2xs font-semibold">
              {(member.display_name || member.username).slice(0, 1).toUpperCase()}
            </span>
            <span className="min-w-0">
              <span className="block truncate">{member.display_name || member.username}</span>
              {member.display_name && <span className="block truncate text-ui-2xs text-muted-foreground">@{member.username}</span>}
            </span>
          </button>
        )}
      </menu.Portal>
    </div>
  );
}
