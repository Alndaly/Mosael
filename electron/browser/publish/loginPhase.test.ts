/**
 * 登录的显式状态机(P3):opening → waiting → verifying → bound / failed(原因)。
 *
 * 它只回答「现在到哪一步了、为什么停」—— 视频号那几轮排查卡在没有这个,只有一句
 * 「not logged in yet at <url>」。
 */
import { describe, expect, it } from "vitest";

// CommonJS is intentional: publishWorker 加载的是同一份。
// eslint-disable-next-line @typescript-eslint/no-require-imports
const { createLoginFlow } = require("./loginPhase.cjs") as {
  createLoginFlow: (options?: { now?: () => number; onChange?: (s: unknown) => void }) => {
    state: () => { phase: string; reason: string; detail: string; checks: number; lastError: string; terminal: boolean };
    opened: () => boolean;
    verifying: () => boolean;
    notYet: (where?: string) => boolean;
    checkFailed: (error: unknown) => boolean;
    bound: () => boolean;
    fail: (reason: string, detail?: string) => boolean;
    isTerminal: () => boolean;
  };
};

describe("登录状态机", () => {
  it("正常一条线:打开 → 提问 → 还没登录 → 再问 → 认出来了", () => {
    const flow = createLoginFlow();
    expect(flow.state().phase).toBe("opening");
    flow.opened();
    expect(flow.state().phase).toBe("waiting");
    flow.verifying();
    expect(flow.state().phase).toBe("verifying");
    flow.notYet("https://channels.weixin.qq.com/login.html");
    expect(flow.state().phase).toBe("waiting");
    expect(flow.state().detail).toContain("channels.weixin.qq.com");
    flow.verifying();
    flow.bound();
    expect(flow.state()).toMatchObject({ phase: "bound", terminal: true, checks: 2 });
  });

  it("判据抛错不判失败(页面可能还在加载),但错误留下来", () => {
    const flow = createLoginFlow();
    flow.opened();
    flow.verifying();
    flow.checkFailed(new Error("evaluate timed out"));
    expect(flow.state().phase).toBe("waiting");
    expect(flow.state().lastError).toBe("evaluate timed out");
  });

  it("失败原因只有这几种,不认识的落成 error", () => {
    for (const reason of ["timeout", "dismissed", "stopped", "error", "switched"]) {
      const flow = createLoginFlow();
      flow.opened();
      flow.fail(reason);
      expect(flow.state()).toMatchObject({ phase: "failed", reason, terminal: true });
    }
    const odd = createLoginFlow();
    odd.opened();
    odd.fail("weird");
    expect(odd.state().reason).toBe("error");
  });

  it("终态不再变:认出来之后判据再怎么说也不动摇", () => {
    const flow = createLoginFlow();
    flow.opened();
    flow.bound();
    expect(flow.verifying()).toBe(false);
    expect(flow.notYet("x")).toBe(false);
    expect(flow.fail("timeout")).toBe(false);
    expect(flow.state()).toMatchObject({ phase: "bound", reason: "" });
  });

  it("状态真的变了才回调(轮询 5 秒一次,不该每次都喊)", () => {
    const seen: string[] = [];
    const flow = createLoginFlow({ onChange: (s) => seen.push((s as { phase: string }).phase) });
    flow.opened();
    flow.verifying();
    flow.notYet("a");
    flow.notYet("a");
    flow.notYet("b");
    flow.bound();
    expect(seen).toEqual(["waiting", "verifying", "waiting", "waiting", "bound"]);
  });
});
