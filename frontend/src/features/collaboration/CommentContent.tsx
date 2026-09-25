/** 一条评论的正文 —— 只渲染,不可编辑。

住在协作域而不是画板里:画板的卡片、工作流的评论列表、右侧的协作面板渲染的是**同一条评论**。
它此前长在 boards/CommentCard 里,于是协作面板要反过来 import 画板才能显示一条评论。
*/
import { EditorContent, useEditor } from "@tiptap/react";

import type { CollaborationComment, WorkspaceMember } from "@/api/client";
import { useExternalContent } from "@/components/app/useExternalContent";
import { cn } from "@/lib/utils";
import { CommentMembers, commentDocument, commentExtensions, COMMENT_TEXT } from "./commentDocument";

export function CommentContent({ comment, members }: { comment: CollaborationComment; members: WorkspaceMember[] }) {
  const editor = useEditor({ extensions: commentExtensions(), content: commentDocument(comment), editable: false,
    editorProps: { attributes: { class: cn(COMMENT_TEXT, "outline-none") } } });
  useExternalContent(editor, (instance) => { instance.commands.setContent(commentDocument(comment), { emitUpdate: false }); }, [comment.body, comment.body_document]);
  return <CommentMembers.Provider value={members}><EditorContent editor={editor} /></CommentMembers.Provider>;
}
