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

vi.mock("@/api/client", () => ({ API_BASE: "http://backend.test", getAuthToken: () => "t" }));

const chunks: string[] = [];
let closeStream: (() => void) | null = null;
vi.mock("@/lib/sse", () => ({
  readSseData: async function* () {
    for (const one of chunks) yield one;
    // 流不主动结束 —— 只有读到 done 的那一方才会跳出循环。这正是要验的那件事。
    await new Promise<void>((resolve) => {
      closeStream = resolve;
    });
  },
}));

const { useAgentTurnStream } = await import("./useAgentTurnStream");

function Probe() {
  const { streamText, attach } = useAgentTurnStream();
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
