import { useMutation } from "@tanstack/react-query";

import { createNoteFromPage } from "@/api/client";
import { useI18n } from "@/app/preferences";
import { openNote } from "@/lib/deepLink";

import type { PageToolsBridge } from "./pageActions";
import type { ToolNotice } from "./useToolNotice";

/**
 * 存成笔记:整页正文(主进程交渲染后的页面,后端挑正文转 Markdown)或选中的文字,带着来源链接与标题。
 * 选中模式下什么都没选就先说一声,不建一篇空笔记。
 */
export function useNoteTools(tools: PageToolsBridge, workspaceId: string, notice: ToolNotice) {
  const t = useI18n();
  const { say, failed } = notice;
  return useMutation({
    mutationFn: async (mode: "article" | "selection") => {
      const read = await tools.readPage(mode);
      if (mode === "selection" && !read.selection) throw new Error(t("browserToolsNoSelection"));
      return createNoteFromPage({ workspace_id: workspaceId, url: read.page.url, title: read.page.title, html: read.html, selection: read.selection });
    },
    onMutate: () => say({ tone: "busy", text: t("browserToolsWorking") }),
    onSuccess: (note) =>
      say({
        tone: "done",
        text: t("browserToolsNoteSaved"),
        action: {
          label: t("browserToolsOpen"),
          run: () => {
            void window.mosaelPublish?.hideView();
            openNote(note.id);
          },
        },
      }),
    onError: failed,
  });
}
