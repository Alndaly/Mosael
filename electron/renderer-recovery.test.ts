/**
 * 主窗口的渲染进程崩了(renderer-recovery.cjs):自动重新载入;一分钟里连崩三次就停下来问人。
 */
import { createRequire } from "node:module";

import { describe, expect, it, vi } from "vitest";

const { createRendererRecovery } = createRequire(import.meta.url)("./renderer-recovery.cjs") as {
  createRendererRecovery: (options: {
    reload: () => void;
    giveUp: (details: { reason: string }) => void;
    schedule?: (callback: () => void, ms: number) => unknown;
  }) => (details: { reason: string; exitCode?: number }) => void;
};

function setup() {
  const reload = vi.fn();
  const giveUp = vi.fn();
  const scheduled: { callback: () => void; ms: number }[] = [];
  const recover = createRendererRecovery({ reload, giveUp, schedule: (callback, ms) => scheduled.push({ callback, ms }) });
  return { reload, giveUp, scheduled, recover };
}

describe("渲染进程崩了之后", () => {
  it("崩了(内存撑爆、被杀)就自动重新载入,不留一块灰窗", () => {
    const { reload, scheduled, recover } = setup();
    recover({ reason: "oom", exitCode: 9 });
    expect(scheduled).toHaveLength(1);
    scheduled[0].callback();
    expect(reload).toHaveBeenCalledOnce();
  });

  it("一分钟里连崩三次之后不再自己重来,问人", () => {
    const { giveUp, scheduled, recover } = setup();
    for (const reason of ["crashed", "crashed", "crashed"]) recover({ reason });
    expect(scheduled).toHaveLength(3);
    recover({ reason: "crashed" });
    expect(scheduled).toHaveLength(3);
    expect(giveUp).toHaveBeenCalledWith({ reason: "crashed" });
  });

  it("正常退出(窗口关了、应用在退)不是崩溃", () => {
    const { giveUp, scheduled, recover } = setup();
    recover({ reason: "clean-exit" });
    expect(scheduled).toEqual([]);
    expect(giveUp).not.toHaveBeenCalled();
  });
});
