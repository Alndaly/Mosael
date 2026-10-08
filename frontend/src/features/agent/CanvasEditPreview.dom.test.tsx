/** @vitest-environment jsdom */
/**
 * 改 ComfyUI 画布那张确认卡(ADR 0042 拍板 3):卡上是一份**人话的改动清单**,不是一坨 ops 的 JSON —— 加了哪几个节点、连了哪几根线
 * (换掉了谁)、改了哪几格(从多少改成多少);子图里的改动写明改的是定义、这张图里用了几处;改前改后的诊断。清单里的节点在工作台的
 * 「助手」里能点了定位(页面引用),别处照样是字。按钮是「应用」。
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, within } from "@testing-library/react";
import React from "react";
import { describe, expect, it, vi } from "vitest";

import type { Confirmation } from "@/api/client";

const api = vi.hoisted(() => ({ approveConfirmation: vi.fn(async () => ({})), rejectConfirmation: vi.fn(), listConfirmations: vi.fn() }));
vi.mock("@/api/client", async (importOriginal) => ({ ...(await importOriginal<typeof import("@/api/client")>()), ...api }));
vi.mock("@/app/preferences", async () => {
  const { messages } = await import("@/app/messages");
  const zh = messages["zh-CN"] as Record<string, string>;
  return { useI18n: () => (key: string) => zh[key] ?? key, usePreferences: () => ({ locale: "zh-CN" }) };
});

import { MarkdownRefsContext, type MarkdownRefs } from "@/components/markdown/markdownRefs";
import { ConfirmationCard } from "@/features/agent/ConfirmationCard";
import { ConfirmationCenter } from "@/features/agent/ConfirmationCenter";
import { ConfirmationsProvider, PendingConfirmationCard } from "@/features/agent/InlineConfirmations";

const SUB = { id: "bc1c967a", name: "Image Edit (Qwen Image 2.1)", uses: 2 };
const PAYLOAD = {
  instance_id: "i1",
  ops: [],
  workflow: { name: "人像", path: "人像.json", key: "workflows/人像.json", temporary: false },
  changes: [
    { op: "add_node", node: "$l", type: "LoraLoader", widgets: { strength_model: 0.6 }, near: "4" },
    { op: "connect", from: { node: "$l", output: "MODEL", type: "MODEL" }, to: { node: "3", input: "model" },
      replaces: { node: "4", output: "MODEL" } },
    { op: "set_widget", node: "3", type: "KSampler", widget: "steps", before: 20, after: 30 },
    { op: "bypass", node: "9", type: "SaveImage", on: false, before: "bypassed" },
    { op: "set_widget", node: "459:458", type: "KSampler", widget: "denoise", before: 1, after: 0.9, layer: SUB },
    { op: "connect", from: { node: "459:458", output: "LATENT", type: "LATENT" }, to: { node: "@out", input: "LATENT" }, layer: SUB },
  ],
  subgraphs: [SUB],
  structural: false,
  check: { before: { error: 2, warning: 0 }, after: { error: 1, warning: 1 },
           fixed: [{ ref: "3", kind: "combo_not_in_list", cause: "「sampler_name」不在可选的值里" }],
           introduced: [{ ref: "5", kind: "size_not_multiple", severity: "warning", cause: "「width」= 1001 不是 8 的倍数" }] },
};

function card(status = "pending"): Confirmation {
  return {
    id: "c1", workspace_id: "w1", session_id: "s1", tool: "comfy_canvas_edit", allow_tool: "comfy_canvas_edit", permission: "edit",
    summary: "改 ComfyUI 画布上开着的「人像」:6 处改动,一次 Ctrl+Z 就退回去", headline: "改 ComfyUI 画布上开着的「人像」:6 处改动,一次 Ctrl+Z 就退回去",
    warning: "子图「Image Edit (Qwen Image 2.1)」在这张图里用了 2 处:改的是它的定义,每一处都会变", always_asks: false, choices: {},
    summary_key: "confirm_comfyCanvasEdit", summary_params: {}, payload: PAYLOAD, status, result: {}, error: null, error_summary: null, error_detail: null, error_hint: null,
    requested_by: "pi-agent", decision_mode: "manual", decided_by: null, created_at: "2026-10-07T00:00:00Z", resolved_at: null,
  } as Confirmation;
}

describe("改画布那张确认卡", () => {
  it("改动清单是人话:新节点、换掉了谁、从多少改成多少、取消旁路;不再列 changes 的 JSON 字段", () => {
    const { container } = render(<ConfirmationCard item={card()} eyebrow="智能体请求" />);
    const items = [...container.querySelectorAll("[data-change]")].map((one) => one.textContent);
    expect(items).toEqual([
      "加一个 LoraLoader 节点,放在 #4 旁边 (strength_model = 0.6)",
      "把 新节点.MODEL 连到 #3.model(换掉原来接着的 #4.MODEL)",
      "#3(KSampler)的「steps」:20 → 30",
      "取消旁路 #9(SaveImage)",
      "#459:458(KSampler)的「denoise」:1 → 0.9",
      "把 #459:458.LATENT 连到子图的输出口「LATENT」",
    ]);
    expect(container.querySelector("dl"), "通用的参数表不画了").toBeNull();
    expect(container.textContent).toContain("检查:改之前 2 个错误、0 个提醒 → 改之后 1 个错误、1 个提醒");
    expect(container.textContent).toContain("会修好 1 个:");
    expect(container.textContent).toContain("会多出 1 个提醒:");
  });

  it("子图里的改动单独一组,写明这张图里用了几处、每一处都会变;卡上的提示也说", () => {
    const { container } = render(<ConfirmationCard item={card()} eyebrow="智能体请求" />);
    const shared = container.querySelector("[data-subgraph-uses]")!;
    expect(shared.getAttribute("data-subgraph-uses")).toBe("2");
    expect(shared.textContent).toBe("在子图「Image Edit (Qwen Image 2.1)」里 —— 这张图里用了 2 处,改的是定义,每一处都会变:");
    expect(screen.getByRole("note").textContent).toContain("用了 2 处");
  });

  it("在工作台的「助手」里,清单里的节点能点了定位(页面引用);新节点没有编号", () => {
    const located: string[] = [];
    const refs: MarkdownRefs = {
      rewrite: (text) => text,
      render: (node, children) => <button type="button" onClick={() => located.push(node)}>{children}</button>,
    };
    render(<MarkdownRefsContext.Provider value={refs}><ConfirmationCard item={card()} eyebrow="智能体请求" /></MarkdownRefsContext.Provider>);
    fireEvent.click(screen.getAllByRole("button", { name: "#459:458" })[0]);
    expect(located).toEqual(["459:458"]);
    expect(screen.queryByRole("button", { name: "#$l" })).toBeNull();
  });

  it("按钮是「应用」:对话里的内联卡和右上角的全局中心都是", async () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    api.listConfirmations.mockResolvedValue([card()]);
    const inline = render(
      <QueryClientProvider client={client}>
        <ConfirmationsProvider sessionId="s1" workspaceId="w1" readOnly={false} live={false}>
          <PendingConfirmationCard item={card()} />
        </ConfirmationsProvider>
      </QueryClientProvider>,
    );
    const actions = await within(inline.container).findByRole("button", { name: /应用/ });
    expect(actions.textContent).toContain("应用");
    expect(within(inline.container).queryByRole("button", { name: /允许一次/ })).toBeNull();
    inline.unmount();
    const center = render(<QueryClientProvider client={client}><ConfirmationCenter workspaceId="w1" /></QueryClientProvider>);
    expect(await within(center.container).findByRole("button", { name: /应用/ })).toBeTruthy();
  });
});
