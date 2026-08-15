/**
 * 轨迹统计的底线:**未知不能变成 0**。
 *
 * 这条线在这个仓库上反复被撞:「还没探测过」被显示成「跑不起来」、「供应商没报」被显示成
 * 「命中率 0%」。两者都是拿一个未知冒充一个结论,而假的精确值比空位难发现得多 —— 没人会去
 * 质疑一个写着 0% 的数字。写这个文件的过程中我自己也先写出了一版把「没报缓存」算成 0 的
 * cacheTokens,所以这里的断言不是补形式,是拦真事。
 */
import { describe, expect, it } from "vitest";

import type { AgentUsageEvent } from "@/features/ai-studio/messageUsage";
import { buildTurns, traceStats } from "./traceModel";
import { deriveTraceTimeline } from "./traceTimeline";

function message(overrides: Partial<Parameters<typeof buildTurns>[0][number]> = {}) {
  return {
    id: "m1",
    role: "assistant",
    content: "",
    created_at: "2026-08-15T10:00:10.000Z",
    payload: {},
    ...overrides,
  };
}

function usage(units: Record<string, unknown>): AgentUsageEvent {
  return {
    id: "u1",
    agent_message_id: "m1",
    provider: "p",
    model: "m",
    capability: "chat",
    operation: "chat",
    status: "succeeded",
    duration_seconds: null,
    units,
    cost_micros: null,
    currency: "USD",
    cost_confidence: "exact",
  };
}

const tool = (over: Record<string, unknown> = {}) => ({
  type: "tool" as const,
  tool: {
    id: "t1",
    name: "web_search",
    args: { query: "美股" },
    status: "done" as const,
    result: "结果",
    usage: { started_at: "2026-08-15T10:00:01.000Z", duration_seconds: 2 },
    ...over,
  },
});

describe("轨迹统计", () => {
  it("没有用量事件时 token 是未知,不是 0", () => {
    const turns = buildTurns([message({ role: "user", content: "你好" }), message()]);
    const stats = traceStats(turns, []);
    expect(stats.inputTokens).toBeNull();
    expect(stats.outputTokens).toBeNull();
  });

  it("供应商不报缓存时命中率是未知,不是 0%", () => {
    const turns = buildTurns([message({ role: "user", content: "你好" }), message()]);
    // 有用量事件、也有 input token —— 唯独没有 cache 字段。这正是「0% 命中」最容易被误报的情形。
    const stats = traceStats(turns, [usage({ input_tokens: 1000, output_tokens: 50 })]);
    expect(stats.inputTokens).toBe(1000);
    expect(stats.cacheReadTokens).toBeNull();
    expect(stats.cacheHitRate).toBeNull();
  });

  it("报了缓存就照实算命中率", () => {
    const turns = buildTurns([message({ role: "user", content: "你好" }), message()]);
    const stats = traceStats(turns, [usage({ input_tokens: 200, cache_read_tokens: 800 })]);
    expect(stats.cacheHitRate).toBeCloseTo(0.8, 5);
  });

  it("老会话没有首 token 打点时不参与平均", () => {
    const turns = buildTurns([
      message({ id: "u", role: "user", content: "a" }),
      message({ id: "a1", payload: { usage: { duration_seconds: 10 } } }),
      message({ id: "u2", role: "user", content: "b" }),
      message({ id: "a2", payload: { usage: { duration_seconds: 10, first_token_seconds: 2 } } }),
    ]);
    const stats = traceStats(turns, []);
    // 只有一轮记到了 —— 平均值就是那一轮,而不是 (0 + 2) / 2。
    expect(stats.firstTokenSeconds).toBe(2);
    expect(stats.firstTokenSamples).toBe(1);
  });

  it("模型耗时是总时长减工具,且不会为负", () => {
    const turns = buildTurns([
      message({ id: "u", role: "user", content: "a" }),
      message({ id: "a1", payload: { usage: { duration_seconds: 10 }, timeline: [tool()] } }),
    ]);
    const stats = traceStats(turns, []);
    expect(stats.toolSeconds).toBe(2);
    expect(stats.llmSeconds).toBe(8);

    // 工具并行时相加会超过轮时长 —— 夹到 0,而不是显示一个负的模型耗时。
    const overlapping = buildTurns([
      message({ id: "u", role: "user", content: "a" }),
      message({
        id: "a1",
        payload: {
          usage: { duration_seconds: 3 },
          timeline: [tool(), tool({ id: "t2" })],
        },
      }),
    ]);
    expect(traceStats(overlapping, []).llmSeconds).toBe(0);
  });

  it("按用户消息分轮,提问本身算这一轮的第一条记录", () => {
    const turns = buildTurns([
      message({ id: "u1", role: "user", content: "第一问" }),
      message({ id: "a1", payload: { timeline: [tool()] } }),
      message({ id: "u2", role: "user", content: "第二问" }),
    ]);
    expect(turns).toHaveLength(2);
    expect(turns[0].events[0].kind).toBe("user");
    expect(turns[0].events[1].kind).toBe("tool");
    expect(turns[1].events).toHaveLength(1);
  });
});

describe("送进模型的那一半", () => {
  it("上下文注入单独成条,不混在提问里", () => {
    // 实际发出去的是 `_prompt_with_context(content, context)` —— content 只是它的一半。
    // 不单独记的话,「它凭什么知道我选中了哪个素材」在轨迹上无迹可寻。
    const turns = buildTurns([
      message({ id: "u1", role: "user", content: "改一下这段", payload: { context: "当前在编辑器,选中 clip-7" } }),
    ]);
    expect(turns[0].events.map((event) => event.kind)).toEqual(["user", "context"]);
    expect(turns[0].events[1].text).toContain("clip-7");
  });

  it("系统提示排在这一轮的执行之前 —— 它是输入不是产物", () => {
    const turns = buildTurns([
      message({ id: "u1", role: "user", content: "问" }),
      message({
        id: "a1",
        payload: { prompt: { system: "你是助手…", hash: "abc" }, timeline: [tool()] },
      }),
    ]);
    expect(turns[0].events.map((event) => event.kind)).toEqual(["user", "system", "tool"]);
  });

  it("没变的那些轮不会各自多出一条系统提示", () => {
    // 后端只在变化时写 prompt 键(host._prompt_snapshot),这里验证前端照此渲染 —— 三轮一条。
    const turns = buildTurns([
      message({ id: "u1", role: "user", content: "a" }),
      message({ id: "a1", payload: { prompt: { system: "S", hash: "h1" } } }),
      message({ id: "u2", role: "user", content: "b" }),
      message({ id: "a2", payload: {} }),
      message({ id: "u3", role: "user", content: "c" }),
      message({ id: "a3", payload: {} }),
    ]);
    expect(turns.flatMap((turn) => turn.events).filter((event) => event.kind === "system")).toHaveLength(1);
  });

  it("没有用量事件时轮级 token 是未知,不是全零", () => {
    const turns = buildTurns([
      message({ id: "u1", role: "user", content: "a" }),
      message({ id: "a1", payload: {} }),
    ]);
    expect(turns[0].usage).toBeNull();

    const withUsage = buildTurns(
      [message({ id: "u1", role: "user", content: "a" }), message({ id: "a1", payload: {} })],
      [],
      [{ ...usage({ input_tokens: 120, output_tokens: 30 }), agent_message_id: "a1" }],
    );
    expect(withUsage[0].usage).toEqual({ input: 120, output: 30, cacheRead: null });
  });
});

describe("轨迹概览投影", () => {
  it("一条时间戳都没有时,顺序投影照样画得出来", () => {
    const turns = buildTurns([
      message({ id: "u1", role: "user", content: "问" }),
      message({ id: "a1", payload: { timeline: [{ type: "text", text: "答" }] } }),
    ]);
    expect(deriveTraceTimeline(turns, "sequence")?.spans).toHaveLength(2);
    // 时长投影没有可用的时间戳 → null,渲染层据此提示换个投影,而不是画一条空轴。
    expect(deriveTraceTimeline(turns, "duration")).toBeNull();
  });

  it("时长投影挤掉操作之间的空闲", () => {
    const turns = buildTurns([
      message({ id: "u1", role: "user", content: "问" }),
      message({
        id: "a1",
        created_at: "2026-08-15T10:01:00.000Z",
        payload: {
          usage: { duration_seconds: 60 },
          timeline: [
            tool({ id: "t1", usage: { started_at: "2026-08-15T10:00:00.000Z", duration_seconds: 1 } }),
            // 两次工具之间空了 30 秒(模型在想)。
            tool({ id: "t2", usage: { started_at: "2026-08-15T10:00:31.000Z", duration_seconds: 1 } }),
          ],
        },
      }),
    ]);
    const model = deriveTraceTimeline(turns, "duration");
    expect(model).not.toBeNull();
    // 轮条覆盖了整段,所以工具之间并没有"没人干活"的空当 —— 压缩量为 0 才是对的。
    expect(model!.compressedIdleMs).toBe(0);
    expect(model!.spans.some((span) => span.kind === "turn")).toBe(true);
  });
});
