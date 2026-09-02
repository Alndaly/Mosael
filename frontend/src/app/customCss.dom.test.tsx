/** @vitest-environment jsdom */
/**
 * 自定义 CSS 能不能压过应用样式,全看**注入的那个 `<style>` 排在哪**。
 *
 * CSS 的规则是:无层级 > 任何 `@layer`,同层级再比出现顺序。所以这段必须无层级、而且排在
 * `<head>` 最后。「插进去就完事」是不够的 —— Vite 在开发模式下会不断把 HMR 的样式插进
 * `<head>`,插在我们后面就把我们压掉了,表现为「改完 CSS 有时生效有时不生效」。
 *
 * 这条钉三件事:注入、始终在最后、以及关掉开关后不留残余样式。
 */

// 这条测试是一道**棘轮**:它进 docs/CONVENTIONS.md 的清单,由 scripts/sync-ratchet-docs.py 生成。
export const RATCHET = true;

import { render, waitFor } from "@testing-library/react";
import React from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { CustomCssProvider, useCustomCss } from "@/app/customCss";

const STYLE_ID = "mosael-custom-css";

let pushChange: ((css: string) => void) | undefined;

function installBridge(css: string) {
  (window as unknown as { mosaelDesktop?: unknown }).mosaelDesktop = {
    platform: "darwin",
    customCss: {
      read: vi.fn().mockResolvedValue(css),
      path: vi.fn().mockResolvedValue("/Users/x/Library/Application Support/Mosael/custom.css"),
      open: vi.fn().mockResolvedValue("/x/custom.css"),
      reveal: vi.fn().mockResolvedValue("/x/custom.css"),
      onChange: (cb: (css: string) => void) => {
        pushChange = cb;
        return () => {
          pushChange = undefined;
        };
      },
    },
  };
}

function styleEl(): HTMLStyleElement | null {
  return document.getElementById(STYLE_ID) as HTMLStyleElement | null;
}

/** 探针:把状态摊到 DOM 上,顺便拿到 setEnabled。 */
let api: ReturnType<typeof useCustomCss> | undefined;
function Probe() {
  api = useCustomCss();
  return <span data-testid="path">{api.path}</span>;
}

const renderApp = () =>
  render(
    <CustomCssProvider>
      <Probe />
    </CustomCssProvider>,
  );

beforeEach(() => {
  document.head.innerHTML = "";
  localStorage.clear();
  api = undefined;
  pushChange = undefined;
});

afterEach(() => {
  delete (window as unknown as { mosaelDesktop?: unknown }).mosaelDesktop;
});

describe("自定义 CSS 的注入", () => {
  it("内容注入进一个无层级的 style,并且排在 head 最后", async () => {
    installBridge(":root { --primary: hotpink; }");
    renderApp();

    await waitFor(() => expect(styleEl()?.textContent).toContain("hotpink"));
    expect(styleEl()!.textContent).not.toContain("@layer");
    expect(document.head.lastElementChild).toBe(styleEl());
  });

  it("别人往 head 末尾插东西之后,它会挪回最后一个", async () => {
    installBridge("body { color: red; }");
    renderApp();
    await waitFor(() => expect(styleEl()?.textContent).toContain("red"));

    // 模拟 Vite 的 HMR:往 head 末尾追加一段样式。
    const intruder = document.createElement("style");
    intruder.textContent = "body { color: blue; }";
    document.head.append(intruder);
    expect(document.head.lastElementChild).toBe(intruder); // 这一刻我们确实被压在前面

    await waitFor(() => expect(document.head.lastElementChild).toBe(styleEl()));
  });

  it("存盘推送新内容后跟着更新", async () => {
    installBridge("body { color: red; }");
    renderApp();
    await waitFor(() => expect(styleEl()?.textContent).toContain("red"));

    pushChange?.("body { color: green; }");
    await waitFor(() => expect(styleEl()!.textContent).toContain("green"));
    expect(styleEl()!.textContent).not.toContain("red");
  });

  it("关掉开关就不留任何样式,但文件内容还记着", async () => {
    installBridge("body { color: red; }");
    renderApp();
    await waitFor(() => expect(styleEl()?.textContent).toContain("red"));

    api!.setEnabled(false);
    await waitFor(() => expect(styleEl()!.textContent).toBe(""));
    expect(api!.css).toContain("red"); // 只是没加载,不是丢了

    api!.setEnabled(true);
    await waitFor(() => expect(styleEl()!.textContent).toContain("red"));
  });

  it("开关状态记在 localStorage 里,逐设备", async () => {
    installBridge("body { color: red; }");
    const first = renderApp();
    await waitFor(() => expect(styleEl()?.textContent).toContain("red"));
    api!.setEnabled(false);
    await waitFor(() => expect(styleEl()!.textContent).toBe(""));
    first.unmount();

    document.head.innerHTML = "";
    renderApp();
    await waitFor(() => expect(api?.css).toContain("red"));
    expect(styleEl()?.textContent ?? "").toBe("");
  });

  it("没有桌面端桥接时不注入,也不报错", async () => {
    renderApp();
    await waitFor(() => expect(api?.supported).toBe(false));
    expect(styleEl()).toBeNull();
  });
});
