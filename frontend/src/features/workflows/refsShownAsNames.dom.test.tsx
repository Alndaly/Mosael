/** @vitest-environment jsdom */
/**
 * **运行时拼出来的说明里也不出现 `{{…}}`**:引用一律说成「节点标题 · 输出」。
 *
 * 静态文案表那一半见 app/messages.noTemplateSyntax.test。这里管的是带着引用拼出来的几处 —— 检查器顶部的「失效引用」
 * 和「重新指向」菜单、「输出变量」那一档、就绪检查的提示(画布角标、就绪清单)、画布上引用提示线的悬停说明。
 * 此前它们原样摆着 `{{gone.text}}`、`{{start.topic}}`,而同一个面板里别处的引用早就是标签了。
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, within } from "@testing-library/react";
import React from "react";
import { beforeAll, describe, expect, it, vi } from "vitest";

const toasts = vi.hoisted(() => ({ success: vi.fn() }));
vi.mock("sonner", () => ({ toast: Object.assign(vi.fn(), { success: toasts.success, error: vi.fn(), message: vi.fn(), info: vi.fn(), warning: vi.fn() }) }));
vi.mock("@xyflow/react", async (original) => ({
  ...(await original<typeof import("@xyflow/react")>()),
  NodeToolbar: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
}));

import { messages } from "@/app/messages";

const zh = messages["zh-CN"];
vi.mock("@/app/preferences", () => ({
  useI18n: () => (key: keyof typeof zh) => zh[key],
  usePreferences: () => ({ locale: "zh-CN" }),
}));

import { ReactFlowProvider } from "@xyflow/react";

import type { WorkflowGraph, WorkflowNodeType } from "@/api/client";
import type { MessageKey } from "@/app/messages";
import { TooltipProvider } from "@/components/ui/tooltip";
import { analyzeWorkflow, type AnalyzeContext } from "@/features/workflows/analyze";
import { referenceHints, toReferenceHintEdges } from "@/features/workflows/referenceHints";
import { workflowIssueText } from "@/features/workflows/workflowCanvasModel";
import { workflowRefNamer } from "@/features/workflows/workflowRefCatalog";
import { NodeInspector } from "@/features/workflows/WorkflowsView";

// 这条测试是一道**棘轮**:它进 docs/CONVENTIONS.md 的清单。
export const RATCHET = true;

beforeAll(() => {
  vi.stubGlobal("ResizeObserver", class { observe() {} unobserve() {} disconnect() {} });
  vi.stubGlobal("IntersectionObserver", class { observe() {} unobserve() {} disconnect() {} });
  vi.stubGlobal("fetch", async () => new Response("[]", { status: 200, headers: { "content-type": "application/json" } }));
});

const t = ((key: MessageKey) => zh[key]) as (key: MessageKey) => string;

function meta(type: string, config: Record<string, unknown>, outputs: string[], extra: Partial<WorkflowNodeType> = {}): WorkflowNodeType {
  return { type, label: type, description: "", category: "", config, outputs, output_types: {}, output_labels: {}, plugin_name: "", tool_name: "", ...extra };
}

const REGISTRY = new Map<string, WorkflowNodeType>([
  ["start", meta("start", { params: { type: "object", editor: "start_params", required_list: "required_params" } }, ["*params"])],
  ["llm", meta("llm", { prompt: { type: "template" } }, ["text", "json"], { output_labels: { text: "文本", json: "JSON" } })],
  ["template", meta("template", { template: { type: "template" } }, ["text"], { output_labels: { text: "文本" } })],
  [
    "loop_foreach",
    meta("loop_foreach", { items: { type: "template" }, body: { type: "graph" }, output: { type: "template" } }, ["results"], {
      body_scope: { loop: ["item", "index"] },
    }),
  ],
]);

const NOTHING_LOADED: AnalyzeContext = {
  chatProfileIds: new Set(),
  chatProfilesLoaded: false,
  generationVendors: new Set(),
  generationModelsLoaded: false,
};

//: 一张图凑齐几种带引用的提示:引用了删掉的节点、开始节点没有的参数、循环体里作用域没有的字段、没接进流程却被引用。
const GRAPH: WorkflowGraph = {
  nodes: [
    { id: "start", type: "start", name: "填主题", config: { params: { topic: "猫" } } },
    { id: "plan", type: "llm", name: "写分镜", config: { prompt: "{{start.topic}} {{start.nope}} {{gone.text}}" } },
    { id: "props", type: "template", name: "可用的道具", config: { template: "桌子" } },
    { id: "set", type: "template", name: "布景", config: { template: "{{plan.text}} {{props.text}}" } },
    {
      id: "loop",
      type: "loop_foreach",
      name: "逐镜",
      config: {
        items: "{{plan.json}}",
        output: "",
        body: { nodes: [{ id: "shot", type: "template", name: "一镜", config: { template: "{{loop.itme}}" } }], edges: [] },
      },
    },
  ],
  edges: [
    { id: "e1", source: "start", target: "plan" },
    { id: "e2", source: "plan", target: "set" },
    { id: "e3", source: "plan", target: "loop" },
  ],
};

describe("就绪检查的提示", () => {
  const { issues } = analyzeWorkflow(GRAPH, REGISTRY, NOTHING_LOADED);
  const withRefs = issues.filter((issue) => issue.ref || issue.refs?.length);

  it("带引用的几种提示都在这张图里", () => {
    expect(new Set(withRefs.map((issue) => issue.code))).toEqual(
      new Set(["stale-var", "start-param-missing", "scope-field-missing", "unwired-referenced"]),
    );
  });

  it("引用说成「节点标题 · 输出」,不摆双括号", () => {
    const name = workflowRefNamer(GRAPH, REGISTRY);
    const texts = new Map(withRefs.map((issue) => [issue.code, workflowIssueText(t, issue, REGISTRY, undefined, name)]));
    for (const text of texts.values()) expect(text).not.toContain("{{");
    expect(texts.get("stale-var")).toContain("gone · text");
    expect(texts.get("start-param-missing")).toContain("填主题 · nope");
    expect(texts.get("scope-field-missing")).toContain("loop · itme");
    expect(texts.get("scope-field-missing")).toContain("loop · item");
    expect(texts.get("unwired-referenced")).toContain("可用的道具 · 文本");
  });

  it("没给引用目录的地方也不摆双括号(按路径分段)", () => {
    for (const issue of withRefs) expect(workflowIssueText(t, issue, REGISTRY)).not.toContain("{{");
  });
});

describe("画布上引用提示线的悬停说明", () => {
  it("说的是「节点标题 · 输出」", () => {
    const hints = referenceHints(GRAPH, REGISTRY, { entryIsRoot: false });
    const edges = toReferenceHintEdges(hints, {
      shape: "default",
      t,
      nodeName: (id) => GRAPH.nodes.find((node) => node.id === id)?.name ?? id,
      refName: workflowRefNamer(GRAPH, REGISTRY),
    });
    expect(edges.length).toBeGreaterThan(0);
    for (const edge of edges) expect(edge.data?.title).not.toContain("{{");
    expect(edges.map((edge) => edge.data?.title).join("\n")).toContain("可用的道具 · 文本");
  });
});

describe("检查器", () => {
  function renderInspector(nodeId: string) {
    const node = GRAPH.nodes.find((one) => one.id === nodeId)!;
    render(
      <QueryClientProvider client={new QueryClient()}>
        <TooltipProvider>
          <ReactFlowProvider>
            <NodeInspector node={node} meta={REGISTRY.get(node.type)!} graph={GRAPH} registry={REGISTRY} workspaceId="w1"
                           onChange={vi.fn()} onApplyGraph={vi.fn()} />
          </ReactFlowProvider>
        </TooltipProvider>
      </QueryClientProvider>,
    );
  }

  it("顶上的「失效引用」和「重新指向」菜单:引用是标签,指不到的是错误态,不摆双括号", async () => {
    renderInspector("plan");
    const notice = screen.getByText(zh.wfStaleRefsTitle).parentElement!;
    const stale = notice.querySelector<HTMLElement>("[data-ref-token]")!;
    expect(stale.textContent).toBe("gone · text");
    expect(stale.dataset.refProblem).toBe("node");
    expect(stale.title).toBe(zh.wfRefMissingNode.replace("{node}", "gone"));
    expect(notice.textContent).not.toContain("{{");
    fireEvent.click(within(notice).getByRole("button", { name: zh.wfRepoint }));
    const menu = await screen.findByText("填主题 · topic");
    expect(menu.closest("[role=dialog], [data-radix-popper-content-wrapper]")?.textContent).not.toContain("{{");
  });

  it("「输出变量」那一档:显示成标签,点一下照旧复制引用,提示里也是名字", () => {
    const writeText = vi.fn(async () => undefined);
    Object.assign(navigator, { clipboard: { writeText } });
    renderInspector("plan");
    fireEvent.click(screen.getByRole("button", { name: zh.wfOutputs }));
    const copy = screen.getByRole("button", { name: zh.wfCopyRef.replace("{name}", "写分镜 · 文本") });
    expect(copy.textContent).toBe("写分镜 · 文本");
    expect(copy.closest("[data-output-refs]")?.textContent).not.toContain("{{");
    fireEvent.click(copy);
    expect(writeText).toHaveBeenCalledWith("{{plan.text}}");
    expect(toasts.success).toHaveBeenLastCalledWith(zh.wfRefCopied, { description: "写分镜 · 文本" });
  });
});
