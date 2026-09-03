import { Notification } from "electron";

import { IPC } from "../ipc-contract.cjs";
import type { Capability, SystemContext } from "./types";

/**
 * 任务完成的系统通知。
 *
 * 关键规则:**窗口有焦点时不发**。渲染层的 TaskCenter 本来就会在任务结束时弹应用内 toast,
 * 你正看着界面的时候再来一条系统通知,是同一件事说两遍。系统通知要解决的是另一个场景 ——
 * 应用被收进托盘 / 切到别的 app 去了,这时 toast 弹在一个你看不见的窗口里,等于没弹。
 *
 * 所以判定条件是「窗口不可见,或者可见但没焦点」,由主进程判(渲染层的 document.hasFocus()
 * 在窗口隐藏时并不可靠)。
 */

export interface TaskNotice {
  title: string;
  body: string;
}

let context: SystemContext | null = null;

/** 该不该发:窗口不在、藏起来了、最小化了、或者没焦点 —— 都说明用户看不到应用内提示。 */
function userIsLookingAtApp(): boolean {
  const win = context?.getWindow();
  if (!win || win.isDestroyed()) return false;
  return win.isVisible() && !win.isMinimized() && win.isFocused();
}

export function showTaskNotification(notice: TaskNotice): boolean {
  if (!Notification.isSupported()) return false;
  if (userIsLookingAtApp()) return false;
  const notification = new Notification({ title: notice.title, body: notice.body });
  notification.on("click", () => {
    context?.showWindow();
    const win = context?.getWindow();
    // 点通知就该看到那件事本身,而不是落在你上次停留的页面上。TaskCenter 监听这个事件。
    if (win && !win.isDestroyed()) win.webContents.send(IPC.event.openTasks);
  });
  notification.show();
  return true;
}

export const notify: Capability = {
  name: "notify",
  register(ctx) {
    context = ctx;
    return { dispose: () => (context = null) };
  },
};
