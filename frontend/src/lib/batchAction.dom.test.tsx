/** @vitest-environment jsdom */
/**
 * 批量动作只有一种写法(lib/batchAction):逐个发、一次性收;全成了清勾选,有失败的只留失败的那几项并说出来。
 * 此前设置页模型 / 连接的批量启停、删除把失败吞了 —— 勾选照样清掉,像是全成了。
 */
import React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { messages, type MessageKey } from "@/app/messages";

const zh = (key: MessageKey) => messages["zh-CN"][key];
vi.mock("@/app/preferences", async (importOriginal) => ({
  ...(await importOriginal<Record<string, unknown>>()),
  useI18n: () => zh,
}));
vi.mock("sonner", () => ({ toast: Object.assign(vi.fn(), { error: vi.fn(), success: vi.fn() }) }));

import { toast } from "sonner";
import { runBatch, useBatchAction } from "./batchAction";

const wrapper = ({ children }: { children: React.ReactNode }) => (
  <QueryClientProvider client={new QueryClient()}>{children}</QueryClientProvider>
);

function selection() {
  return { clear: vi.fn(), exit: vi.fn(), keepOnly: vi.fn() };
}

beforeEach(() => vi.clearAllMocks());

describe("runBatch", () => {
  it("一个失败不拦着别的,做成的和失败的(带原因)分开交回", async () => {
    const outcome = await runBatch(["a", "b", "c"], async (id) => {
      if (id === "b") throw new Error("busy");
    });
    expect(outcome.done).toEqual(["a", "c"]);
    expect(outcome.failed.map((one) => one.id)).toEqual(["b"]);
    expect(String(outcome.failed[0].reason)).toContain("busy");
  });
});

describe("useBatchAction", () => {
  it("有失败:勾选只留失败的、说成功几项失败几项,不清空", async () => {
    const select = selection();
    const settled = vi.fn();
    const { result } = renderHook(
      () => useBatchAction({ run: async (id) => { if (id !== "a") throw new Error("x"); }, selection: select, onSettled: settled }),
      { wrapper },
    );
    act(() => result.current.mutate({ ids: ["a", "b", "c"] }));
    await waitFor(() => expect(select.keepOnly).toHaveBeenCalledWith(["b", "c"]));
    expect(select.clear).not.toHaveBeenCalled();
    expect(toast.error).toHaveBeenCalledWith(zh("bulkPartialFailed").replace("{ok}", "1").replace("{failed}", "2"));
    expect(settled).toHaveBeenCalledTimes(1);
  });

  it("全成了:清勾选(exitOnSuccess 时退出选择模式),有完成提示就说;额外参数交给每一次", async () => {
    const select = selection();
    const run = vi.fn(async () => undefined);
    const { result } = renderHook(
      () => useBatchAction<boolean>({ run, selection: select, exitOnSuccess: true, doneMessage: (n) => `done ${n}` }),
      { wrapper },
    );
    act(() => result.current.mutate({ ids: ["a", "b"], extra: true }));
    await waitFor(() => expect(select.exit).toHaveBeenCalled());
    expect(run).toHaveBeenCalledWith("a", true);
    expect(select.keepOnly).not.toHaveBeenCalled();
    expect(toast.success).toHaveBeenCalledWith("done 2");
  });
});
