/**
 * 工作流库「在编辑器里打开」(ADR 0035 §4)。
 *
 * - 桌面版:主进程在这个连接自己的内嵌视图里打开它的 ComfyUI 界面,再打开那一张(`mosaelBrowser.openComfyWorkflow`,
 *   分区由主进程按连接 id 拼,脚本是写死的);没打开成(那台机器上没有这一张、页面没就绪)就留一句话,回来时看得到;
 * - 网页版(没有那座桥)或不认识的编辑器:新标签页打开它的地址。ComfyUI 的地址打不开某一张存着的工作流,所以说清楚
 *   在左边「工作流」里点开哪一张;
 * - **回来时刷新**:在 ComfyUI 里存了改动、换了模型,Mosael 这边跟着变 —— 桌面版是我们开的那个内嵌视图收起时,
 *   网页版是这个标签页重新拿到焦点时,各调一次 `onReturn`。
 */
import React from "react";

import type { PluginInstance, WorkflowFile, WorkflowLibrary } from "@/api/client";
import { errorText } from "@/api/errorMessage";

export type WorkflowEditor = NonNullable<WorkflowLibrary["editor"]>;

/** 打开之后要告诉用户的那句话(`path` 是哪一张的;详情页只显示自己那一张的)。 */
export type EditorNote =
  | { kind: "missing" | "notReady" | "tab"; path: string }
  | { kind: "error"; path: string; message: string };

/** 这个 ComfyUI 连接的内嵌视图分区 —— 和主进程契约拼的是同一个(electron/ipc-contract.cjs parseComfyWorkflow)。 */
export const editorPartition = (instanceId: string) => `persist:pool-comfyui-${instanceId}`;

/** 这个界面开得了内嵌视图里的 ComfyUI 吗(桌面版、主进程是带这座桥的那一版)。 */
export const embeddedEditor = (editor: WorkflowEditor) =>
  editor.kind === "comfyui" && typeof window.mosaelBrowser?.openComfyWorkflow === "function";

export function useWorkflowEditor(instance: PluginInstance, onReturn: () => void) {
  const [note, setNote] = React.useState<EditorNote | null>(null);
  const [opening, setOpening] = React.useState(false);
  //: 打开过、还没回来:开的是内嵌视图还是新标签页;`shown`:我们开的那个内嵌视图已经亮出来过(收起时才算回来)
  const away = React.useRef<"view" | "tab" | null>(null);
  const shown = React.useRef(false);
  const returned = React.useRef(onReturn);
  React.useEffect(() => {
    returned.current = onReturn;
  }, [onReturn]);

  React.useEffect(() => {
    const partition = editorPartition(instance.id);
    const back = () => {
      away.current = null;
      shown.current = false;
      returned.current();
    };
    const stopView = window.mosaelPublish?.onViewState?.((state) => {
      if (away.current !== "view") return;
      if (state.visible) shown.current = state.accountId === partition;
      else if (shown.current) back();
    });
    // 网页版开的是新标签页:回到这个标签页就算回来
    const onFocus = () => {
      if (away.current === "tab") back();
    };
    window.addEventListener("focus", onFocus);
    return () => {
      stopView?.();
      window.removeEventListener("focus", onFocus);
    };
  }, [instance.id]);

  const open = async (editor: WorkflowEditor, flow: WorkflowFile) => {
    setNote(null);
    if (!embeddedEditor(editor)) {
      window.open(editor.url, "_blank", "noopener,noreferrer");
      away.current = "tab";
      setNote({ kind: "tab", path: flow.path });
      return;
    }
    // 先记下「出去了」:视图在桥回话之前就亮出来了
    away.current = "view";
    shown.current = false;
    setOpening(true);
    try {
      const result = await window.mosaelBrowser!.openComfyWorkflow({
        connectionId: instance.id,
        url: editor.url,
        name: instance.name,
        path: flow.path,
      });
      if (!result.ok) {
        away.current = null;
        setNote({ kind: "error", path: flow.path, message: result.error ?? "" });
      } else if (result.outcome && result.outcome !== "opened") {
        setNote({ kind: result.outcome === "missing" ? "missing" : "notReady", path: flow.path });
      }
    } catch (error) {
      away.current = null;
      setNote({ kind: "error", path: flow.path, message: errorText(error) });
    } finally {
      setOpening(false);
    }
  };

  return { open, opening, note, dismiss: () => setNote(null) };
}
