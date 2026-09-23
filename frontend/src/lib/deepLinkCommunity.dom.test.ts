/** @vitest-environment jsdom */
/**
 * 官网「在 Mosael 中打开」的深链到了应用里,要落到**具体那一项**:没装的插件 → 插件页 + 市场里找到它;
 * 没添加的模板 → 工作流页 + 社区里选中它。只导航:装、添加仍由人点。
 */
import { afterEach, expect, it, vi } from "vitest";

import { listenDesktopDeepLinks, OPEN_PLUGIN_IN_MARKET, OPEN_WORKFLOW_TEMPLATE } from "./deepLink";

let stop: (() => void) | undefined;
afterEach(() => stop?.());

function follow(detail: Record<string, string>) {
  const heard: Array<[string, string]> = [];
  for (const name of [OPEN_PLUGIN_IN_MARKET, OPEN_WORKFLOW_TEMPLATE]) {
    window.addEventListener(name, (event) => heard.push([name, (event as CustomEvent<string>).detail]), { once: true });
  }
  stop = listenDesktopDeepLinks(vi.fn());
  window.dispatchEvent(new CustomEvent("mosael:deep-link", { detail }));
  return heard;
}

it("没装的插件:切到插件页,请市场找到它", () => {
  const heard = follow({ view: "plugins", market: "dev.mosael.remotion" });
  expect(window.location.hash).toBe("#/plugins");
  expect(heard).toEqual([[OPEN_PLUGIN_IN_MARKET, "dev.mosael.remotion"]]);
});

it("没添加的模板:切到工作流页,请社区选中它", () => {
  const heard = follow({ view: "workflows", template: "product_pitch_short" });
  expect(window.location.hash).toBe("#/workflows");
  expect(heard).toEqual([[OPEN_WORKFLOW_TEMPLATE, "product_pitch_short"]]);
});
