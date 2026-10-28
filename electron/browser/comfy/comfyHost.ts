// ComfyUI 工作台(ADR 0038 §3)在主进程这一侧:亮出连接的内嵌视图、开一个工作台会话(注入桥、轮询),
// 替面板向桥要东西,渲染层换了文档时把工作台视图收起来。
//
// 视图借的是视图宿主那一套(views/viewHost):工作台只是**一种用法**,不是发布执行器的一部分。
// 此前这一段写在 publish/publishWorker 里,RPA 动作「工作台调用」为此要 import 发布执行器。
import type { BaseWindow } from "electron";

import { hostedViews, openPoolLogin } from "../views/viewHost";
import { newWorkflowInPage, openWorkflowInPage, type ComfyNewOutcome, type ComfyOpenOutcome } from "./comfyEditor";
import type { ComfyNavigation, NavigationOutcome } from "./comfyNavigation";
import { comfyViewOpening, comfyViewShown, setComfyNavigation } from "./comfyViews";
import type { WorkbenchCall, WorkbenchCallResult, WorkbenchState } from "./comfyWorkbench";
import { WorkbenchSessions } from "./comfyWorkbenchSessions";

/** 工作台的会话:主进程轮询内嵌画布里的桥,交给渲染层。 */
let workbench: WorkbenchSessions | null = null;

/** 开始接工作台。视图宿主要先建好(见 views/viewHost.startViewHost)。 */
export function startComfyHost(opts: {
  window: BaseWindow;
  /** 桥那边看到的(选中、脏标记、能力、事件);`state: null` 是会话结束了。 */
  onWorkbench?: (update: { connectionId: string; state: WorkbenchState | null }) => void;
}): void {
  if (workbench) return;
  workbench = new WorkbenchSessions({
    driver: (partition) => hostedViews()?.existingDriver(partition) ?? null,
    visible: (partition) => hostedViews()?.visibleAccountId === partition,
    paused: () => opts.window.isDestroyed() || !opts.window.isVisible() || opts.window.isMinimized(),
    emit: (partition, state) =>
      opts.onWorkbench?.({ connectionId: partition.slice(COMFY_PARTITION_PREFIX.length), state }),
  });
}

export function stopComfyHost(): void {
  workbench = null;
}

const COMFY_PARTITION_PREFIX = "persist:pool-comfyui-";

/** 开工作台的结果:打开了那一张 / 新建了一张 / 只是回到画布,或者没成的原因(那台机器上没有这一张、这版前端没有「新建」命令……)。 */
export type WorkbenchOpenOutcome = ComfyOpenOutcome | ComfyNewOutcome;

/**
 * ComfyUI 工作台(ADR 0038 §3):亮出这个连接的内嵌视图(还开着就接着用,不重新载入 —— 那边可能有没存的改动),开始一个工作台
 * 会话(注入桥、轮询),再打开 `workflows/<path>` 那一张、或者执行前端自己的「新建」命令新建一张、或者什么都不开(回到画布上
 * 开着的那张),见 comfyEditor。工作流库里打开一张、「新建」都走这里;和池档案登录同一个前台单槽。
 */
export async function openComfyWorkbench(opts: {
  partition: string;
  url: string;
  name: string;
  path: string | null;
  fresh: boolean;
}): Promise<WorkbenchOpenOutcome> {
  const driver = await showComfyView(opts);
  if (!driver || !workbench) return "notReady";
  workbench.start(opts.partition, new URL(opts.url).origin);
  if (opts.path) return openWorkflowInPage(driver, { url: opts.url, path: opts.path });
  if (opts.fresh) return newWorkflowInPage(driver, { url: opts.url });
  return "opened";
}

/** 工作台面板要桥做的一件事(填值、刷新下拉、导出、保存、写标记)。会话不在就不做。 */
export function comfyWorkbenchCall(opts: { partition: string; call: WorkbenchCall }): Promise<WorkbenchCallResult> {
  if (!workbench) return Promise.resolve({ ok: false, error: "closed" });
  return workbench.call(opts.partition, opts.call);
}


/** 亮出一个 ComfyUI 连接的内嵌视图(还开着就接着用):先记下来源、装上设置写回的闸,亮出来之后挂上「载入完」的监听。 */
async function showComfyView(opts: { partition: string; url: string; name: string }) {
  comfyViewOpening(opts.partition, opts.url);
  await openPoolLogin({ partition: opts.partition, url: opts.url, name: opts.name || undefined, resume: true });
  comfyViewShown(opts.partition);
  return hostedViews()?.existingDriver(opts.partition) ?? null;
}

/** 内嵌 ComfyUI 画布的操控方式(触控板 / 鼠标,见 comfyNavigation):只在这个视图里生效,每次载入之后再设一次。 */
export function setComfyViewNavigation(opts: { partition: string; mode: ComfyNavigation }): Promise<NavigationOutcome> {
  return setComfyNavigation(opts.partition, opts.mode);
}

/**
 * 主窗口换了一份文档(重新加载、HMR 整页刷新、出错后点「重新加载」、渲染进程崩了):前台要是**工作台**的 ComfyUI 视图,就收起来、
 * 停掉工作台会话。
 *
 * 原生视图亮着时,渲染层必须画着和它配套的那一圈:工作台是顶栏加右边那一列,普通网页是内嵌浏览器的顶栏。普通网页的那一圈
 * 只看视图状态就画得回来(主进程补播、preload 记着最新的一帧);工作台那一页却是渲染层自己的状态 —— 开的是哪个连接、在哪个
 * 工作区、哪个页签、这次跑过的几次 —— 新的那一份文档里都没有,认领不了那个视图。留着它,就是一块没有顶栏、没有那一列的
 * 光秃秃的画布盖在应用上(维护者截图)。收起的视图本身还活着:「在工作台里打开」回到同一张,没存的改动还在。
 */
export function releaseWorkbenchView(): void {
  const partition = hostedViews()?.visibleAccountId;
  if (!partition || !workbench?.active(partition)) return;
  workbench.stop(partition, false);
  hostedViews()?.hide();
}
