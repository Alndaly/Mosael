/**
 * 浏览器会话顶栏的「页面工具」作用在谁身上:**只能是前台那个视图**(见 AccountViewManager.foreground)。
 *
 * 渲染层不点名要哪个视图 —— 它看得见的只有前台这一个。全部是用户在顶栏上点出来的一次性动作,不自动、
 * 不批量、不在后台跑。字节交回渲染层,由它带着出处传给后端入库(后端那一侧有鉴权、类型与大小的闸);这一侧
 * 不碰后端:主进程手里只有执行器的共享密钥,没有「谁在用」的用户会话,素材该记在谁名下它说不清。
 */
import type { WebContents } from "electron";

import { sharedViews } from "./accountViews";
import type { PageInfo } from "./pageToolsCore";

export class PageToolError extends Error {
  /** 给渲染层认的原因码;要给人看的话由渲染层按码去文案表里取。 */
  constructor(readonly code: "no_page" | "capture_failed" | "full_page_unavailable") {
    super(`page-tools: ${code}`);
    this.name = "PageToolError";
  }
}

export type Foreground = { id: string; webContents: WebContents; partition: string };

export function foreground(): Foreground {
  const target = sharedViews()?.foreground();
  if (!target) throw new PageToolError("no_page");
  return target;
}

export function pageOf(wc: WebContents): PageInfo {
  return { url: wc.getURL(), title: wc.getTitle() };
}

/** 侧栏开合(视频清单、图片网格):前台视图右侧让出这么宽,侧栏画在网页旁边而不是底下。 */
export function setToolsInset(right: number): void {
  sharedViews()?.setShellInset(right);
}
