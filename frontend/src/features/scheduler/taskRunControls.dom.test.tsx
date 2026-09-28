/** @vitest-environment jsdom */

/**
 * 绑的工作流被删了的任务,开关打不开、「立即运行」点不动。
 *
 * 真机反馈:页面上写着「绑定的工作流已删除」,开关却照样打得开、「立即运行」照样点得动 ——
 * 每点一次,运行记录里多一条 0.0 秒的失败。后端现在会拒绝(scheduler.ensure_runnable),
 * 界面不该先摆出一个点了只会报错的按钮。但**关**永远要关得掉。
 */

import React from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

vi.mock("@/app/preferences", () => ({
  useI18n: () => (key: string) =>
    ({
      runNow: "立即运行",
      runStatus_running: "运行中",
      pluginOn: "启用",
      pluginOff: "停用",
      taskBlockedWorkflowGone: "绑定的工作流已删除,这个任务不能启用或运行",
    })[key] ?? key,
  usePreferences: () => ({ locale: "zh" }),
}));

import { hasActiveRun, TaskRunControls } from "./taskRunControls";

function mount(enabled: boolean, blocked: boolean, running = false) {
  const onRun = vi.fn();
  const onToggle = vi.fn();
  render(<TaskRunControls enabled={enabled} blocked={blocked} running={running} onRun={onRun} onToggle={onToggle} />);
  return { onRun, onToggle, run: screen.getByRole("button", { name: /立即运行|运行中/ }), toggle: screen.getByRole("switch") };
}

describe("跑不起来的任务", () => {
  it("停着的:开关打不开,立即运行点不动,悬停说清为什么", () => {
    const { run, toggle, onRun, onToggle } = mount(false, true);
    expect((run as HTMLButtonElement).disabled).toBe(true);
    expect((toggle as HTMLButtonElement).disabled).toBe(true);
    fireEvent.click(toggle);
    fireEvent.click(run);
    expect(onToggle).not.toHaveBeenCalled();
    expect(onRun).not.toHaveBeenCalled();
    expect(run.parentElement?.getAttribute("title")).toBe("绑定的工作流已删除,这个任务不能启用或运行");
    expect(toggle.closest("label")?.getAttribute("title")).toBe("绑定的工作流已删除,这个任务不能启用或运行");
  });

  it("还开着的(不变式之前留下的):不能跑,但关得掉", () => {
    const { run, toggle, onToggle } = mount(true, true);
    expect((run as HTMLButtonElement).disabled).toBe(true);
    expect((toggle as HTMLButtonElement).disabled).toBe(false);
    fireEvent.click(toggle);
    expect(onToggle).toHaveBeenCalledWith(false);
  });
});

describe("跑得起来的任务", () => {
  it("启用着:能跑、能关,没有多余的说明", () => {
    const { run, toggle, onRun } = mount(true, false);
    expect((run as HTMLButtonElement).disabled).toBe(false);
    expect((toggle as HTMLButtonElement).disabled).toBe(false);
    fireEvent.click(run);
    expect(onRun).toHaveBeenCalledTimes(1);
    expect(run.parentElement?.getAttribute("title")).toBeNull();
  });

  it("停着:能打开,但停着的时候不能立即运行(和后端 schedErr_disabled 一致)", () => {
    const { run, toggle, onToggle } = mount(false, false);
    expect((run as HTMLButtonElement).disabled).toBe(true);
    fireEvent.click(toggle);
    expect(onToggle).toHaveBeenCalledWith(true);
  });
});

//: 定时任务不重入(后端 has_active_run 拒绝)。此前按钮的转圈只跟着「这一次请求」:请求几十毫秒就回来,
//: 任务还在跑,按钮又能点了 —— 连点就是一串 409。现在按任务实际有没有一次在跑判。
describe("有一次还在跑", () => {
  it("按钮说「运行中」、点不动", () => {
    const { run, onRun } = mount(true, false, true);
    expect(run.textContent).toContain("运行中");
    expect((run as HTMLButtonElement).disabled).toBe(true);
    fireEvent.click(run);
    expect(onRun).not.toHaveBeenCalled();
  });

  it("排队中和运行中都算在跑,跑完的不算(和后端 ACTIVE_RUN_STATUSES 一致)", () => {
    expect(hasActiveRun([{ status: "queued" }])).toBe(true);
    expect(hasActiveRun([{ status: "succeeded" }, { status: "running" }])).toBe(true);
    expect(hasActiveRun([{ status: "succeeded" }, { status: "failed" }, { status: "cancelled" }])).toBe(false);
    expect(hasActiveRun(undefined)).toBe(false);
  });
});
