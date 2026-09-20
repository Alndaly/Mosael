/** @vitest-environment jsdom */

/**
 * 整页点不动的那把锁。
 *
 * 这是用户报的「无限画布有时候整个点不动、拖不动」:画面一切正常,但什么都点不动,只能刷新。
 * 锁在 `<body>` 上,所以盖住的是整个应用,不是画布。
 *
 * 此前的兜底长在 `ModalShell` 里,漏掉的正是画布上最常见的那两种 —— 这里各钉一条。
 */
import { afterEach, describe, expect, it, vi } from "vitest";

import { hasOpenOverlay, isStalePointerLock, watchBodyPointerLock } from "./bodyPointerLock";

function lock() {
  document.body.style.pointerEvents = "none";
}
function openDialog() {
  const el = document.createElement("div");
  el.setAttribute("role", "dialog");
  el.setAttribute("data-state", "open");
  document.body.appendChild(el);
  return el;
}

afterEach(() => {
  document.body.innerHTML = "";
  document.body.style.pointerEvents = "";
  vi.useRealTimers();
});

describe("落下的 body 指针锁", () => {
  it("有浮层开着时那把锁不是落下的 —— 别动它", () => {
    lock();
    openDialog();
    expect(hasOpenOverlay()).toBe(true);
    expect(isStalePointerLock()).toBe(false);
  });

  it("没浮层却锁着 = 被落下了", () => {
    lock();
    expect(isStalePointerLock()).toBe(true);
  });

  it("没锁就没什么可兜的", () => {
    openDialog();
    expect(isStalePointerLock()).toBe(false);
  });

  it("浮层**还开着就被卸载**时解锁 —— 画布点一下空白处就是这种", async () => {
    // 提示词面板挂在「当前选中的那一项」上,取消选中就整块卸载;里面开着的 Select 没有
    // 机会走关闭流程,锁就留下了。此前的兜底看的是 open→false,而这里 open 自始至终是 true。
    vi.useFakeTimers();
    const dialog = openDialog();
    lock();
    const stop = watchBodyPointerLock(document, 10);
    dialog.remove(); // 开着就被卸载
    await vi.advanceTimersByTimeAsync(50);
    expect(document.body.style.pointerEvents).toBe("");
    stop();
  });

  it("关掉之后马上卸载也解锁", async () => {
    // 此前那份兜底把检查排在 250ms 之后,而它的清理函数会在卸载时把定时器取消 ——
    // 关掉、紧接着卸载,那一次检查永远不会跑。
    vi.useFakeTimers();
    const dialog = openDialog();
    lock();
    const stop = watchBodyPointerLock(document, 10);
    dialog.setAttribute("data-state", "closed");
    dialog.remove();
    await vi.advanceTimersByTimeAsync(50);
    expect(document.body.style.pointerEvents).toBe("");
    stop();
  });

  it("正在开着的模态不会被误解锁", async () => {
    vi.useFakeTimers();
    openDialog();
    lock();
    const stop = watchBodyPointerLock(document, 10);
    await vi.advanceTimersByTimeAsync(50);
    expect(document.body.style.pointerEvents).toBe("none");
    stop();
  });

  it("停下之后不再插手", async () => {
    vi.useFakeTimers();
    const stop = watchBodyPointerLock(document, 10);
    stop();
    lock();
    await vi.advanceTimersByTimeAsync(50);
    expect(document.body.style.pointerEvents).toBe("none");
  });
});
