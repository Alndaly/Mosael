import React from "react";

import { leaveNativeView } from "@/lib/nativeView";

/**
 * 邀请链接(ADR 0054)在客户端这一侧:链接长什么样、从一段文字里认出码、打开之后「待处理的那一张」放在哪。
 *
 * 链接有两种样子,带的是同一串码:
 * - **网页地址** `https://<部署>/#/join/<码>` —— 对方可能还没装客户端。部署管理员在管理页配了网页地址就用它;
 *   没配、而这个界面本身就是网页版(开在 http(s) 上、不是桌面端)时用自己这个地址;桌面单机两样都没有,不给;
 * - **深链** `mosael://open?join=<码>` —— 装了桌面端的人点开,应用被叫到前台(见 electron/system/deepLink)。
 *
 * 打开之后码先记在 sessionStorage 里(「待处理的那一张」):还没登录时登录页据此说「X 邀请你加入 Y」、注册时带上它;
 * 登录之后工作区那一层兑现它(加入、切过去,见 app/App 的 useJoinFromInvite)。不放进地址栏 —— 地址会被书签、历史、
 * 截图带走,而它就是凭据。
 */

//: 和后端 secrets.token_urlsafe 的字符集一致;长度留宽。
const CODE = /^[A-Za-z0-9_-]{8,200}$/;
const JOIN_HASH = /^#\/join\/([A-Za-z0-9_-]{8,200})\/?$/;
const PENDING_KEY = "mosael.pendingInvite";

export type InviteLinkUrls = {
  /** 网页地址;没有网页版时是 null。 */
  web: string | null;
  /** 桌面端深链。 */
  app: string;
};

export function inviteLinkUrls(
  code: string,
  webUrl: string,
  here: Pick<Location, "protocol" | "origin" | "pathname"> = window.location,
  desktop: boolean = Boolean(window.mosaelDesktop),
): InviteLinkUrls {
  const app = `mosael://open?join=${encodeURIComponent(code)}`;
  const base = webUrl.trim().replace(/\/+$/, "");
  if (base) return { web: `${base}/#/join/${code}`, app };
  if (!desktop && /^https?:$/.test(here.protocol)) return { web: `${here.origin}${here.pathname}#/join/${code}`, app };
  return { web: null, app };
}

/** 从一段文字里认出邀请码:裸码、网页地址(`#/join/<码>`)、深链(`join=<码>`)都认。认不出就原样(去掉空白)交回。 */
export function codeFromInviteText(text: string): string {
  const value = text.trim();
  const fromHash = value.match(/#\/join\/([A-Za-z0-9_-]{8,200})/);
  if (fromHash) return fromHash[1];
  const fromQuery = value.match(/[?&]join=([A-Za-z0-9_-]{8,200})/);
  if (fromQuery) return fromQuery[1];
  return value;
}

const listeners = new Set<() => void>();

function notify() {
  for (const listener of listeners) listener();
}

export function pendingInvite(): string | null {
  try {
    const code = sessionStorage.getItem(PENDING_KEY);
    return code && CODE.test(code) ? code : null;
  } catch {
    return null;
  }
}

export function setPendingInvite(code: string): void {
  if (!CODE.test(code)) return;
  try {
    sessionStorage.setItem(PENDING_KEY, code);
  } catch {
    //: 隐私模式写不进去:这一次就认不住了 —— 不报错,登录之后对方可以再点一次链接。
  }
  notify();
}

export function clearPendingInvite(): void {
  try {
    sessionStorage.removeItem(PENDING_KEY);
  } catch {
    /* 同上 */
  }
  notify();
}

/** 待处理的那一张邀请;没有是 null。随 set / clear 重渲染。 */
export function usePendingInvite(): string | null {
  return React.useSyncExternalStore(
    (listener) => {
      listeners.add(listener);
      return () => listeners.delete(listener);
    },
    pendingInvite,
    () => null,
  );
}

/**
 * 启动时看一眼地址:是 `#/join/<码>` 就把码记成待处理的那一张,地址换回首页(码不留在地址栏里)。
 * 要在路由读地址之前调(见 main.tsx):路由不认识 `join`,会把它当成首页覆盖掉。
 */
export function captureInviteFromLocation(location: Location = window.location, history: History = window.history): void {
  const match = location.hash.match(JOIN_HASH);
  if (!match) return;
  setPendingInvite(match[1]);
  history.replaceState(null, "", `${location.pathname}${location.search}#/home`);
}

/** 桌面端深链 `mosael://open?join=<码>`:主进程转成 `mosael:deep-link` 事件(detail.join)。登录前也要接得住,所以在
 *  启动时挂一次,而不是挂在登录之后才有的工作台里。
 *
 *  加入之后切到那个工作区:内嵌浏览器、工作台在前台的话先收起来(和别的深链一样,ADR 0051 D35),不然切换发生在网页底下。 */
export function listenInviteDeepLinks(): () => void {
  const onLink = (event: Event) => {
    const join = (event as CustomEvent<{ join?: string }>).detail?.join;
    if (typeof join !== "string") return;
    void leaveNativeView();
    setPendingInvite(join);
  };
  window.addEventListener("mosael:deep-link", onLink);
  return () => window.removeEventListener("mosael:deep-link", onLink);
}
