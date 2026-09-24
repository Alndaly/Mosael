import { getOpenAtLogin, isHiddenLaunch, setOpenAtLogin } from "./loginItem";
import { badge } from "./badge";
import {
  customCss,
  customCssPath,
  ensureCustomCss,
  openCustomCss,
  readCustomCss,
  revealCustomCss,
} from "./customCss";
import { deepLinkFromArgv, parseDeepLink } from "./deepLink";
import { notify, showTaskNotification } from "./notify";
import { power } from "./power";
import { adoptSecondInstance, protocol } from "./protocol";
import { shortcuts } from "./shortcuts";
import { isQuitting, markQuitting, residency } from "./residency";
import { tray } from "./tray";
import { setLocale as setMessagesLocale } from "../i18n.cjs";
import { EMPTY_STATUS, type Capability, type CapabilityHandle, type SystemContext, type SystemStatus } from "./types";

/**
 * 系统能力注册表。
 *
 * 每个能力一个模块、一个 register(ctx),main.cjs 只负责遍历——而不是继续往那个已经很长的
 * 文件里堆 Tray/powerSaveBlocker/登录项的代码。加一个能力 = 加一个文件加一行,摘掉一个能力
 * 也一样,不用在几百行里找它散落在哪几处。
 *
 * 状态是**推**进来的(pushStatus),不是拉出去的:系统层不认识后端,也不知道「任务」是什么,
 * 它只知道有个数字叫 runningJobs。这样托盘文案、Dock 角标、防睡眠都吃同一份快照,而这一层
 * 始终能被单独测。
 */

const CAPABILITIES: Capability[] = [residency, power, tray, badge, notify, protocol, shortcuts, customCss];

/** 已注册、还没 dispose 的能力。语言变化要挨个告诉它们(托盘菜单是它自己画的字)。 */
const live = new Set<CapabilityHandle>();

/**
 * 界面语言变了。本 bundle 打包了自己那份 i18n.cjs(状态不和 main.cjs 共享),所以由主进程
 * 转告;注册之前调也行 —— 那时只是把语言定下来,托盘一建出来就是对的语言。
 */
export function setLocale(locale: string): void {
  setMessagesLocale(locale);
  for (const handle of live) {
    try {
      handle.onLocale?.();
    } catch (err) {
      console.warn("[system] locale update failed:", err);
    }
  }
}

export interface SystemHandle {
  pushStatus: (status: SystemStatus) => void;
  dispose: () => void;
}

export function registerSystemCapabilities(ctx: SystemContext): SystemHandle {
  const handles: CapabilityHandle[] = [];
  for (const capability of CAPABILITIES) {
    try {
      const handle = capability.register(ctx);
      if (handle) {
        handles.push(handle);
        live.add(handle);
      }
    } catch (err) {
      // 一个能力挂掉不该带走其他能力,更不该拦住应用启动:托盘建不出来,应用照常能用。
      console.warn(`[system] capability ${capability.name} failed to register:`, err);
    }
  }

  let last: SystemStatus = EMPTY_STATUS;
  return {
    pushStatus(status) {
      last = { ...last, ...status };
      for (const handle of handles) {
        try {
          handle.onStatus?.(last);
        } catch (err) {
          console.warn("[system] status dispatch failed:", err);
        }
      }
    },
    dispose() {
      for (const handle of handles) {
        live.delete(handle);
        try {
          handle.dispose?.();
        } catch {
          /* 退出路径上,尽力而为 */
        }
      }
    },
  };
}

export {
  adoptSecondInstance,
  customCssPath,
  deepLinkFromArgv,
  ensureCustomCss,
  openCustomCss,
  readCustomCss,
  revealCustomCss,
  getOpenAtLogin,
  isHiddenLaunch,
  isQuitting,
  markQuitting,
  parseDeepLink,
  setOpenAtLogin,
  showTaskNotification,
};
export type { SystemContext, SystemStatus };
