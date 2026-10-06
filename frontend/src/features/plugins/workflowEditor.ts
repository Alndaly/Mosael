/**
 * 工作流库里打开一张(ADR 0035 §4)和「新建」(ADR 0038 §8)。只有一个入口,开到哪里看这个界面开不开得了工作台:
 *
 * - **桌面版**:开的是工作台(全屏:左边是这个连接自己的内嵌视图里的 ComfyUI 画布,右边是 Mosael 的面板,见 comfy-workbench)。
 *   此前旁边还有一个「在编辑器里打开」,开的是同一个画布、只是不带面板 —— 两个入口开的是同一样东西(维护者:「应该仅仅一个
 *   工作台就够了吧」),面板收起来就是它。没开成(那台机器上没有这一张、页面没就绪、这版前端没有「新建」命令)就留一句话,
 *   回来时看得到;
 * - **网页版**(没有内嵌视图):「在 ComfyUI 里打开」开新标签页。ComfyUI 的地址打不开某一张存着的工作流,所以说清楚在左边
 *   「工作流」里点开哪一张;「新建」也开新标签页,说在 ComfyUI 里点「新建」。存盘是 ComfyUI 自己的;
 * - **回来时刷新**:在 ComfyUI 里存了改动、换了模型、存了新的一张,Mosael 这边跟着变 —— 桌面版是我们开的那个内嵌视图
 *   收起时,网页版是这个标签页重新拿到焦点时,各调一次 `onReturn`。
 */
import React from "react";

import type { PluginInstance, WorkflowFile, WorkflowLibrary } from "@/api/client";
import { errorText } from "@/api/errorMessage";
import { openWorkbench, workbenchAvailable } from "@/features/plugins/workbench/workbenchSession";
import { explainOpenFailure } from "@/features/plugins/localServiceStatus";
import { comfyPartition } from "@/features/plugins/comfyNavigation";

export type WorkflowEditor = NonNullable<WorkflowLibrary["editor"]>;

/**
 * 打开之后要告诉用户的那句话(`path` 是哪一张的;详情页只显示自己那一张的)。新建的那几句 `path` 是空的,摆在列表上面:
 * 这版前端没有「新建」命令(`unsupported`)、页面没就绪(`notReady`)、开了新标签页(`newTab`)。
 */
export type EditorNote =
  | { kind: "missing" | "notReady" | "tab" | "unsupported" | "newTab" | "starting"; path: string }
  | { kind: "error"; path: string; message: string };

/** 新建的那几句话(`path` 是空的):摆在工作流库列表上面,不在某一张的详情里。 */
export const NEW_NOTE_PATH = "";

/** 这个界面开得了 ComfyUI 工作台吗(桌面版):开得了就只有「在工作台里打开」,开不了就只有「在 ComfyUI 里打开」(新标签页)。 */
export const embeddedWorkbench = (editor: WorkflowEditor) => editor.kind === "comfyui" && workbenchAvailable();

export function useWorkflowEditor(instance: PluginInstance, onReturn: () => void, workspaceId = "") {
  const [note, setNote] = React.useState<EditorNote | null>(null);
  //: 正在开哪一张(新建是 `NEW_NOTE_PATH`):转圈的是开它的那颗按钮,别的在这期间点不了。网页版开新标签页是当场的,不算
  const [opening, setOpening] = React.useState<string | null>(null);
  //: 打开过、还没回来:开的是内嵌视图还是新标签页;`shown`:我们开的那个内嵌视图已经亮出来过(收起时才算回来)
  const away = React.useRef<"view" | "tab" | null>(null);
  const shown = React.useRef(false);
  const returned = React.useRef(onReturn);
  React.useEffect(() => {
    returned.current = onReturn;
  }, [onReturn]);

  React.useEffect(() => {
    const partition = comfyPartition(instance.id);
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

  /** 页面没就绪:背后的本机服务此刻用不了就说它那一句(不应答、起不来……),否则照「没就绪」说。 */
  const notReady = async (path: string) => {
    const said = await explainOpenFailure(instance.id, "");
    setNote(said ? { kind: "error", path, message: said } : { kind: "notReady", path });
  };

  /**
   * 在工作台里打开这一张(`flow`),或者在工作台里新建一张(`flow` 为 null)。没开成、那台机器上没有这一张、这版前端没有「新建」
   * 命令,都留一句话;视图收起时照样刷新。连接背后是停着的本机服务时,先摆一句「正在启动」,起好了收掉。
   */
  const workbench = async (editor: WorkflowEditor, flow: WorkflowFile | null) => {
    setNote(null);
    const path = flow?.path ?? NEW_NOTE_PATH;
    away.current = "view";
    shown.current = false;
    setOpening(path);
    try {
      const result = await openWorkbench(
        { instanceId: instance.id, instanceName: instance.name, workspaceId, url: editor.url },
        flow ? { path: flow.path } : { fresh: true },
        () => setNote({ kind: "starting", path }),
      );
      setNote((now) => (now?.kind === "starting" ? null : now));
      if (!result.ok) {
        away.current = null;
        setNote({ kind: "error", path, message: await explainOpenFailure(instance.id, result.error) });
      } else if (result.outcome === "missing") {
        setNote({ kind: "missing", path });
      } else if (result.outcome === "unsupported") {
        setNote({ kind: "unsupported", path });
      } else if (result.outcome === "notReady" || result.outcome === "elsewhere") {
        await notReady(path);
      }
    } catch (error) {
      away.current = null;
      setNote({ kind: "error", path, message: await explainOpenFailure(instance.id, errorText(error)) });
    } finally {
      setOpening(null);
    }
  };

  /** 网页版:新标签页开这台 ComfyUI,回到这个标签页时刷新;留一句话说在那边点开哪一张(`tab`)、点「新建」(`newTab`)。 */
  const newTab = (editor: WorkflowEditor, said: EditorNote) => {
    window.open(editor.url, "_blank", "noopener,noreferrer");
    away.current = "tab";
    setNote(said);
  };

  /** 打开这一张:桌面版在工作台里,网页版开新标签页(说清楚在左边「工作流」里点开哪一张)。 */
  const open = async (editor: WorkflowEditor, flow: WorkflowFile) => {
    if (embeddedWorkbench(editor)) return workbench(editor, flow);
    newTab(editor, { kind: "tab", path: flow.path });
  };

  /** 新建一张:桌面版在工作台里新建,网页版开新标签页(说在 ComfyUI 里点「新建」)。 */
  const create = async (editor: WorkflowEditor) => {
    if (embeddedWorkbench(editor)) return workbench(editor, null);
    newTab(editor, { kind: "newTab", path: NEW_NOTE_PATH });
  };

  return { open, create, opening, note, dismiss: () => setNote(null) };
}
