/** @vitest-environment jsdom */
import React from "react";
import { act, fireEvent, render } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { readHint } from "@/test/hint";

/**
 * 浏览器会话顶栏里的「需要重启」小标记:网页视图盖住了窗口底部那条过期提示,顶栏里得常驻一个看得见的记号。
 * 主进程过期才出;悬停说明为什么;能替你重启时点一下就重启,不能时只给说明。正式打包的应用永远不出。
 */
vi.mock("@/app/preferences", () => ({
  useI18n: () => (key: string) => key,
}));

type Status = { files: string[]; canRestart: boolean };
let push: (status: Status) => void;
const restart = vi.fn(async () => undefined);

function installBridge(initial: Status) {
  Object.defineProperty(window, "mosaelDesktop", {
    configurable: true,
    value: {
      devMain: {
        status: vi.fn(async () => initial),
        onStale: (callback: (status: Status) => void) => {
          push = callback;
          return () => undefined;
        },
        restart,
      },
    },
  });
}

const { MainStaleBadge } = await import("./MainStaleBadge");
const { mainStale } = await import("./mainStale");

const badge = () => document.querySelector("[data-main-stale-badge]") as HTMLButtonElement | null;

beforeEach(() => {
  restart.mockClear();
  mainStale.reset();
});

describe("顶栏里的「需要重启」小标记", () => {
  it("不过期就没有;产物变了出一个小标记,悬停说明为什么,点一下就重启", async () => {
    installBridge({ files: [], canRestart: true });
    render(<MainStaleBadge />);
    await act(async () => undefined);
    expect(badge()).toBeNull();

    act(() => push({ files: ["publish.bundle.cjs"], canRestart: true }));
    expect(badge()).not.toBeNull();
    expect(badge()!.getAttribute("aria-label")).toBe("mainStaleText");
    expect(await readHint(badge()!)).toBe("mainStaleTextmainStaleBadgeHint");
    fireEvent.click(badge()!);
    expect(restart).toHaveBeenCalled();
  });

  it("不是经 pnpm dev 拉起的(没法替你重启):小标记只给说明,点不了", async () => {
    installBridge({ files: ["main.cjs"], canRestart: false });
    render(<MainStaleBadge />);
    await act(async () => undefined);
    expect(badge()!.disabled).toBe(true);
    expect(await readHint(badge()!)).toBe("mainStaleManualmainStaleCannotRestart");
    fireEvent.click(badge()!);
    expect(restart).not.toHaveBeenCalled();
  });

  it("正式打包的应用(桥上没有 devMain)永远没有", () => {
    Object.defineProperty(window, "mosaelDesktop", { configurable: true, value: {} });
    render(<MainStaleBadge />);
    expect(badge()).toBeNull();
  });
});
