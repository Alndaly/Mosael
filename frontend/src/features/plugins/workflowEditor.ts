/**
 * 工作流库「在编辑器里打开」(ADR 0035 §4)和「新建」(ADR 0038 §8)。
 *
 * - 桌面版:主进程在这个连接自己的内嵌视图里打开它的 ComfyUI 界面,再打开那一张(`mosaelBrowser.openComfyWorkflow`,
 *   分区由主进程按连接 id 拼,脚本是写死的);没打开成(那台机器上没有这一张、页面没就绪)就留一句话,回来时看得到;
 * - 网页版(没有那座桥)或不认识的编辑器:新标签页打开它的地址。ComfyUI 的地址打不开某一张存着的工作流,所以说清楚
 *   在左边「工作流」里点开哪一张;
 * - **新建**:同一个内嵌视图里执行 ComfyUI 前端自己的「新建」命令(和它菜单里「工作流 → 新建」同一条,先探测有没有);
 *   这版前端没有就说清楚、让用户在 ComfyUI 里自己点。网页版开新标签页、说在 ComfyUI 里点「新建」。存盘是 ComfyUI 自己的;
 * - **工作台**(ADR 0038 §8):桌面版能开工作台时,「在工作台里打开」和「新建」开的是工作台(全屏:左边是同一个内嵌视图里的
 *   ComfyUI 画布,右边是 Mosael 的面板,见 comfy-workbench);回来时一样刷新;
 * - **回来时刷新**:在 ComfyUI 里存了改动、换了模型、存了新的一张,Mosael 这边跟着变 —— 桌面版是我们开的那个内嵌视图
 *   收起时,网页版是这个标签页重新拿到焦点时,各调一次 `onReturn`。
 */
import React from "react";

import type { PluginInstance, WorkflowFile, WorkflowLibrary } from "@/api/client";
import { errorText } from "@/api/errorMessage";
import { openWorkbench, workbenchAvailable } from "@/features/plugins/workbench/workbenchSession";
import { readyLocalService } from "@/features/plugins/localServiceReady";
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

/** 这个 ComfyUI 连接的内嵌视图分区 —— 和主进程契约拼的是同一个(electron/ipc-contract.cjs parseComfyWorkflow)。 */
export const editorPartition = comfyPartition;

/** 这个界面开得了内嵌视图里的 ComfyUI 吗(桌面版、主进程是带这座桥的那一版)。 */
export const embeddedEditor = (editor: WorkflowEditor) =>
  editor.kind === "comfyui" && typeof window.mosaelBrowser?.openComfyWorkflow === "function";

/** 这个界面能在内嵌视图里新建吗(主进程是带「新建」那座桥的那一版)。旧主进程没有它时退回新标签页。 */
export const embeddedCreate = (editor: WorkflowEditor) =>
  editor.kind === "comfyui" && typeof window.mosaelBrowser?.newComfyWorkflow === "function";

/** 这个界面开得了 ComfyUI 工作台吗(桌面版、主进程是带工作台那座桥的那一版)。 */
export const embeddedWorkbench = (editor: WorkflowEditor) => editor.kind === "comfyui" && workbenchAvailable();

export function useWorkflowEditor(instance: PluginInstance, onReturn: () => void, workspaceId = "") {
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

  /** 本机服务的连接(ADR 0041):开内嵌视图之前请宿主起好;真要起时摆一句「正在启动」,起好了收掉。 */
  const ready = async (path: string) => {
    await readyLocalService(instance.id, () => setNote({ kind: "starting", path }));
    setNote((now) => (now?.kind === "starting" ? null : now));
  };
  const starting = (path: string) => () => setNote({ kind: "starting", path });
  /** 页面没就绪:背后的本机服务此刻用不了就说它那一句(不应答、起不来……),否则照「没就绪」说。 */
  const notReady = async (path: string) => {
    const said = await explainOpenFailure(instance.id, "");
    setNote(said ? { kind: "error", path, message: said } : { kind: "notReady", path });
  };

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
      await ready(flow.path);
      const result = await window.mosaelBrowser!.openComfyWorkflow({
        connectionId: instance.id,
        url: editor.url,
        name: instance.name,
        path: flow.path,
      });
      if (!result.ok) {
        away.current = null;
        setNote({ kind: "error", path: flow.path, message: await explainOpenFailure(instance.id, result.error ?? "") });
      } else if (result.outcome === "missing") {
        setNote({ kind: "missing", path: flow.path });
      } else if (result.outcome && result.outcome !== "opened") {
        await notReady(flow.path);
      }
    } catch (error) {
      away.current = null;
      setNote({ kind: "error", path: flow.path, message: await explainOpenFailure(instance.id, errorText(error)) });
    } finally {
      setOpening(false);
    }
  };

  /**
   * 在工作台里打开这一张(`flow`),或者在工作台里新建一张(`flow` 为 null)。没开成、那台机器上没有这一张、这版前端没有「新建」
   * 命令,都留一句话;视图收起时照样刷新。
   */
  const workbench = async (editor: WorkflowEditor, flow: WorkflowFile | null) => {
    setNote(null);
    const path = flow?.path ?? NEW_NOTE_PATH;
    away.current = "view";
    shown.current = false;
    setOpening(true);
    try {
      const result = await openWorkbench(
        { instanceId: instance.id, instanceName: instance.name, workspaceId, url: editor.url },
        flow ? { path: flow.path } : { fresh: true },
        starting(path),
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
      setOpening(false);
    }
  };

  /**
   * 新建一张:能开工作台就在工作台里新建;否则内嵌视图里执行 ComfyUI 自己的「新建」命令;网页版(或旧主进程)开新标签页,
   * 说在 ComfyUI 里点「新建」。
   */
  const create = async (editor: WorkflowEditor) => {
    if (embeddedWorkbench(editor)) return workbench(editor, null);
    setNote(null);
    if (!embeddedCreate(editor)) {
      window.open(editor.url, "_blank", "noopener,noreferrer");
      away.current = "tab";
      setNote({ kind: "newTab", path: NEW_NOTE_PATH });
      return;
    }
    away.current = "view";
    shown.current = false;
    setOpening(true);
    try {
      await ready(NEW_NOTE_PATH);
      const result = await window.mosaelBrowser!.newComfyWorkflow({ connectionId: instance.id, url: editor.url, name: instance.name });
      if (!result.ok) {
        away.current = null;
        setNote({ kind: "error", path: NEW_NOTE_PATH, message: result.error ?? "" });
      } else if (result.outcome && result.outcome !== "created") {
        // 视图已经亮着(ComfyUI 照常能用,用户可以自己点「新建」):回来时照样刷新,话留着
        setNote({ kind: result.outcome === "unsupported" ? "unsupported" : "notReady", path: NEW_NOTE_PATH });
      }
    } catch (error) {
      away.current = null;
      setNote({ kind: "error", path: NEW_NOTE_PATH, message: errorText(error) });
    } finally {
      setOpening(false);
    }
  };

  return { open, create, workbench, opening, note, dismiss: () => setNote(null) };
}
