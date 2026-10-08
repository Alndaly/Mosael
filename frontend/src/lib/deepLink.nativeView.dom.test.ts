/** @vitest-environment jsdom */
/**
 * mosael:// 深链落地时,内嵌浏览器、工作台在前台就先把它收起来再跳(ADR 0051 D35)。
 *
 * 真机上:工作台开着时点一个深链,路由在画布底下换成了设置页,工作台纹丝不动 —— 窗口被唤到前台,看不出发生了什么,按「返回 Mosael」
 * 之后才落到设置页。收起和「返回 Mosael」是同一下:视图还活着,工作台里没存的改动还在,所以不另弹确认。
 */
import { afterEach, expect, it, vi } from "vitest";

import { listenDesktopDeepLinks } from "./deepLink";
import { clearPendingInvite, listenInviteDeepLinks, pendingInvite } from "./inviteLinks";
import { resetNativeViewForTests } from "./nativeView";

let stop: (() => void) | undefined;
afterEach(() => {
  stop?.();
  vi.unstubAllGlobals();
  resetNativeViewForTests();
  window.location.hash = "";
});

function desktop(visible: boolean) {
  const order: string[] = [];
  const hideView = vi.fn(async () => {
    order.push(`hideView ${window.location.hash}`);
  });
  vi.stubGlobal("mosaelPublish", {
    onViewState: (callback: (state: { visible: boolean }) => void) => {
      callback({ visible });
      return () => undefined;
    },
    hideView,
  });
  resetNativeViewForTests();
  window.addEventListener("hashchange", () => order.push(`hash ${window.location.hash}`), { once: true });
  stop = listenDesktopDeepLinks(vi.fn());
  return { order, hideView };
}

it("视图在前台:先收起视图,再跳", async () => {
  window.location.hash = "#/plugins";
  const { order, hideView } = desktop(true);
  window.dispatchEvent(new CustomEvent("mosael:deep-link", { detail: { view: "settings" } }));
  await vi.waitFor(() => expect(window.location.hash).toBe("#/settings"));
  expect(hideView).toHaveBeenCalledTimes(1);
  expect(order[0]).toBe("hideView #/plugins");
});

it("视图不在前台:当场就跳,不碰视图", () => {
  const { hideView } = desktop(false);
  window.dispatchEvent(new CustomEvent("mosael:deep-link", { detail: { view: "settings" } }));
  expect(window.location.hash).toBe("#/settings");
  expect(hideView).not.toHaveBeenCalled();
});

it("邀请链接(mosael://open?join=…):先收起视图,再去加入、切过去;别的深链那条不管它", () => {
  const { hideView } = desktop(true);
  const stopInvite = listenInviteDeepLinks();
  try {
    window.dispatchEvent(new CustomEvent("mosael:deep-link", { detail: { view: "home", join: "abcdefgh1234" } }));
    expect(hideView).toHaveBeenCalledTimes(1);
    expect(pendingInvite()).toBe("abcdefgh1234");
  } finally {
    stopInvite();
    clearPendingInvite();
  }
});
