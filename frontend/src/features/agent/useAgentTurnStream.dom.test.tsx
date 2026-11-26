/** @vitest-environment jsdom */
import React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";

/**
 * 「连流 → 攒状态 → 收尾失效」这段状态机**只有一份**,两个聊天面板共用。
 *
 * 它此前各写了一遍,而已经分岔:工作台那份的收尾是 `await Promise.all([...])`(让 running 转
 * false 与正式消息落在同一帧,否则答完一句会闪一下),画布助手那份是 `void` 各发各的 ——
 * 也就是说画布助手每答完一句都闪一下,而那个 bug 在隔壁文件里被诊断过、注释过、修好过。
 *
 * 这几条钉的正是那两处差别:**`done` 真的被读**(此前谁都不读,全靠"流关了"推断),
 * 以及**收尾在两条失效都 settle 之后才清流态**。
 */

const chunks: string[] = [];
//: 一次接流取走一份;空了就用 `chunks`。验「一条流结束了还在跑就再接」要两条不一样的流。
const streams: string[][] = [];
let closeStream: (() => void) | null = null;
vi.mock("@/lib/sse", () => ({
  readSseData: async function* () {
    for (const one of streams.shift() ?? chunks) yield one;
    // 流不主动结束 —— 只有读到 done 的那一方才会跳出循环。这正是要验的那件事。
    await new Promise<void>((resolve) => {
      closeStream = resolve;
    });
  },
}));

const { useAgentTurnStream } = await import("./useAgentTurnStream");

function Probe({ viewed = "s1" }: { viewed?: string }) {
  const { streamText, attach } = useAgentTurnStream(viewed, false);
  React.useEffect(() => {
    void attach("s1");
  }, [attach]);
  return <output aria-label="text">{streamText}</output>;
}

function show(client: QueryClient) {
  render(
    <QueryClientProvider client={client}>
      <Probe />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  chunks.length = 0;
  streams.length = 0;
  closeStream = null;
  vi.stubGlobal("fetch", vi.fn(async () => new Response("ok", { status: 200 })));
});

// 显式超时:不读 done 的话这条流永远不结束,这条就该**快速红掉**。
// 变异验证过:去掉 `if (payload.done) break`,它在 2 秒上红在 waitFor 超时。
it("读 done 就收尾 —— 不靠「流关了」去推断", { timeout: 4000 }, async () => {
  chunks.push(JSON.stringify({ text: "答案", done: false, timeline: [] }));
  chunks.push(JSON.stringify({ text: "答案完整", done: true, timeline: [] }));
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const invalidated: unknown[] = [];
  client.invalidateQueries = (async (args: unknown) => {
    invalidated.push(args);
  }) as typeof client.invalidateQueries;

  show(client);

  // 流**没有**关(closeStream 还没被调用),而收尾已经跑完了 —— 证据是失效已经发出去。
  await waitFor(() => expect(invalidated.length).toBeGreaterThanOrEqual(3), { timeout: 2000 });
  expect(closeStream).toBeNull();
  expect(screen.getByLabelText("text").textContent).toBe("");
});

it("收尾在 messages + session 两条失效都 settle 之后才清流态", async () => {
  chunks.push(JSON.stringify({ text: "答案", done: true, timeline: [] }));
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  let release: (() => void) | null = null;
  const settled = new Promise<void>((resolve) => {
    release = resolve;
  });
  client.invalidateQueries = (async (args: { queryKey?: unknown[] }) => {
    // messages 那条卡住:清流态不许发生在它 settle 之前,否则会露出一帧空白。
    if (Array.isArray(args?.queryKey) && args.queryKey[0] === "agent-messages") await settled;
  }) as typeof client.invalidateQueries;

  show(client);

  await waitFor(() => expect(screen.getByLabelText("text").textContent).toBe("答案"));
  // 还卡着 —— 流态必须还在,临时气泡不能先消失。
  expect(screen.getByLabelText("text").textContent).toBe("答案");

  await act(async () => {
    release?.();
    await Promise.resolve();
  });
  await waitFor(() => expect(screen.getByLabelText("text").textContent).toBe(""));
});

it("steer 边界让段号变化时：立即失效持久消息和队列，不靠轮询等到下一次", { timeout: 4000 }, async () => {
  chunks.push(JSON.stringify({ text: "插话前", segment: 0, done: false, timeline: [] }));
  chunks.push(JSON.stringify({ text: "", segment: 1, done: false, timeline: [] }));
  chunks.push(JSON.stringify({ text: "插话后", segment: 1, done: true, timeline: [] }));
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const invalidated: string[] = [];
  client.invalidateQueries = (async (args: { queryKey?: unknown[] }) => {
    if (Array.isArray(args?.queryKey) && typeof args.queryKey[0] === "string") invalidated.push(args.queryKey[0]);
  }) as typeof client.invalidateQueries;

  show(client);

  await waitFor(() => expect(invalidated).toContain("agent-queue"));
  expect(invalidated).toContain("agent-messages");
});

// 当前会话现在可以从面板外面换掉(另一个面板、免提浮标),面板里没有「切会话」那一刻可以
// 挂 reset —— 所以由这个 hook 自己认:看的不再是这条流的会话,就掐流、清流态。
it("看的会话换成了别的:掐掉手上那条流,流态清空", async () => {
  chunks.push(JSON.stringify({ text: "旧会话的半句", done: false, timeline: [] }));
  const signals: AbortSignal[] = [];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (_url: string, init?: { signal?: AbortSignal }) => {
      if (init?.signal) signals.push(init.signal);
      return new Response("ok", { status: 200 });
    }),
  );
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const view = render(
    <QueryClientProvider client={client}>
      <Probe viewed="s1" />
    </QueryClientProvider>,
  );
  await waitFor(() => expect(screen.getByLabelText("text").textContent).toBe("旧会话的半句"));

  view.rerender(
    <QueryClientProvider client={client}>
      <Probe viewed="s2" />
    </QueryClientProvider>,
  );
  expect(screen.getByLabelText("text").textContent).toBe("");
  expect(signals[0]?.aborted).toBe(true);
});


/** 发送请求可能在用户切走之后才返回；这个晚到的 attach 不该把别的会话的流接上来。 */
function LateAttach({ viewed = "s2", target = "s1" }: { viewed?: string; target?: string }) {
  const { streamText, attach } = useAgentTurnStream(viewed, false);
  React.useEffect(() => {
    void attach(target);
  }, [attach, target]);
  return <output aria-label="late-text">{streamText}</output>;
}

it("晚到的 attach 目标不是当前查看的会话：不接那条流", async () => {
  const fetched = vi.fn(async () => new Response("ok", { status: 200 }));
  vi.stubGlobal("fetch", fetched);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <LateAttach />
    </QueryClientProvider>,
  );
  await act(async () => {
    await Promise.resolve();
    await Promise.resolve();
  });
  expect(fetched).not.toHaveBeenCalled();
  expect(screen.getByLabelText("late-text").textContent).toBe("");
});

/** 面板只告诉它「这个会话在跑」,接流由它自己来 —— 和两个面板的用法一样。 */
function Follower() {
  const { streamText, turnStartedAt } = useAgentTurnStream("s1", true);
  return (
    <>
      <output aria-label="text">{streamText}</output>
      <output aria-label="started">{turnStartedAt?.toISOString() ?? ""}</output>
    </>
  );
}

// 维护者截图:ask_user 等人回答时后端重启,答完之后新的一轮跑了十几分钟,界面还停在那一行、
// 「已用」一路累加。一轮紧接一轮时会话一直是 running,看 running 的跳变来接流就接不上后面那一轮。
// 变异验证过:去掉跟随 effect 里的 `endedStreams` 依赖,它红在等「下一轮」的 waitFor 上。
it("一条流结束了而会话还在跑:自己再接上下一轮,开始时间跟着换成下一轮的", { timeout: 4000 }, async () => {
  streams.push([JSON.stringify({ text: "上一轮", done: true, timeline: [], started_at: "2026-11-15T07:00:00" })]);
  streams.push([JSON.stringify({ text: "下一轮", done: false, timeline: [], started_at: "2026-11-15T07:27:13" })]);
  const fetched = vi.fn(async () => new Response("ok", { status: 200 }));
  vi.stubGlobal("fetch", fetched);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  client.invalidateQueries = (async () => undefined) as typeof client.invalidateQueries;
  render(
    <QueryClientProvider client={client}>
      <Follower />
    </QueryClientProvider>,
  );

  await waitFor(() => expect(screen.getByLabelText("text").textContent).toBe("下一轮"), { timeout: 2000 });
  expect(fetched).toHaveBeenCalledTimes(2);
  // 后端时间不带时区标记,是 UTC —— 经 parseServerTime 解析,不能被当成本地时间。
  expect(screen.getByLabelText("started").textContent).toBe("2026-11-15T07:27:13.000Z");
});
