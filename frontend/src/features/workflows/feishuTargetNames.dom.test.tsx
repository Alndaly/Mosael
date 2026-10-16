/** @vitest-environment jsdom */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import React from "react";
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";

import type { WorkflowGraph } from "@/api/client";
import type { WorkflowNodeData } from "@/features/workflows/WorkflowNode";
import { workflowPortNamer } from "@/features/workflows/portNames";
import { useWorkflowDisplayNodes } from "@/features/workflows/useWorkflowDisplayElements";
import { plainRefName } from "@/features/workflows/workflowRefCatalog";
import { toWorkflowFlowNodes } from "@/features/workflows/workflowCanvasModel";
import { builtinNodeCatalog, uiText } from "@/test/nodeCatalog";

/**
 * 画布卡片上「私聊 ou_1f8ca9…6998」那一行:**真的接上收件人目录之后**写的是名字。
 *
 * 单元那一半在 feishuChannel.test.ts(值 → 那一行怎么写)。这里钉的是它上面那条链:画布那一层
 * (useWorkflowDisplayNodes)去现查 `feishu_targets` 的目录,把「值 → 名字」喂进 workflowNodeSubtitle。
 * 这一跳断了,卡上就退回原始 id —— 而两半各自都绿(维护者报的就是那个样子)。
 */

const T = uiText("zh");
const REGISTRY = builtinNodeCatalog("zh");

function graph(channel: string, to: string): WorkflowGraph {
  return {
    nodes: [{ id: "gate", type: "await_approval", name: "", config: { channel, to }, position: { x: 0, y: 0 } }],
    edges: [],
  } as WorkflowGraph;
}

const asked: string[] = [];

beforeAll(() => {
  vi.stubGlobal("ResizeObserver", class { observe() {} unobserve() {} disconnect() {} });
});

const originalFetch = globalThis.fetch;
afterEach(() => {
  globalThis.fetch = originalFetch;
  asked.length = 0;
});

function cardLine(g: WorkflowGraph, catalog: unknown[]) {
  globalThis.fetch = vi.fn(async (input: RequestInfo | URL) => {
    const url = new URL(String(input), "http://x");
    let body: unknown = [];
    if (url.pathname.endsWith("/workflows/field-options")) {
      asked.push(`${url.searchParams.get("source")}:${url.searchParams.get("parent")}`);
      if (url.searchParams.get("source") === "feishu_targets") body = catalog;
    }
    return new Response(JSON.stringify(body), { status: 200, headers: { "content-type": "application/json" } });
  }) as never;
  const nodes = toWorkflowFlowNodes(g, REGISTRY);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return renderHook(
    () =>
      useWorkflowDisplayNodes({
        nodes,
        graph: g,
        registry: REGISTRY,
        workspaceId: "w1",
        t: T,
        layerIssues: new Map(),
        runByNode: {},
        nodeZ: {},
        markers: [],
        patchMarker: () => {},
        deleteMarker: () => {},
        markerMode: false,
        markersVisible: true,
        annotationMode: false,
        searchHit: null,
        atRoot: true,
        refName: plainRefName,
        portNamer: workflowPortNamer({ registry: REGISTRY, t: T }),
      }),
    { wrapper: ({ children }: { children: React.ReactNode }) => <QueryClientProvider client={client}>{children}</QueryClientProvider> },
  );
}

/** 卡片上那一行 —— 画布投影交下来的那一格(见 WorkflowNode 的 subtitle)。 */
const lineOf = (nodes: Array<{ data: unknown }>) => (nodes[0].data as WorkflowNodeData).configSummary;

describe("画布卡片上的收件人", () => {
  it("目录里有人就写名字,不是那串 open_id", async () => {
    const { result } = cardLine(graph("user", "ou_1f8ca9d0f5b04b1e8a7c6998"), [
      { value: "ou_1f8ca9d0f5b04b1e8a7c6998", label: "张三 · 机器人 A", bot_id: "bot-a" },
    ]);
    await waitFor(() =>
      expect(lineOf(result.current)).toBe("飞书 · 私聊 张三 · 机器人 A"),
    );
  });

  it("目录里没有这个人:照旧写 id,不编名字", async () => {
    const { result } = cardLine(graph("user", "ou_someone"), []);
    await waitFor(() => expect(asked).toContain("feishu_targets:user"));
    expect(lineOf(result.current)).toBe("飞书 · 私聊 ou_someone");
  });

  it("没配成私聊/发群的节点不去问目录", async () => {
    const { result } = cardLine(graph("origin", ""), []);
    await waitFor(() => expect(lineOf(result.current)).toBe("飞书 · 哪来发回哪"));
    expect(asked.filter((one) => one.startsWith("feishu_targets"))).toEqual([]);
  });
});
