/** @vitest-environment jsdom */
//: 上游便签的字填进提示词:框里看得见的和提交出去的是同一段。此前只换了 prompt、没换文档,
//: 提示词框照旧文档画(删空之后留下的空段落)—— 框里空着,提交出去的却是便签那段。
import React from "react";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import type { BoardItem, GenerationOption } from "@/api/client";
import { NodeComposer } from "./NodeComposer";

vi.mock("@/app/preferences", () => ({ useI18n: () => (key: string) => key }));
vi.mock("@xyflow/react", () => ({ NodeToolbar: ({ children }: { children: React.ReactNode }) => children, Position: { Bottom: "bottom" } }));
vi.mock("@tanstack/react-query", () => ({ useQuery: () => ({ data: [] }) }));

afterEach(cleanup);

const model = {
  id: "m", provider_profile_id: "p", profile_name: "T", label: "L", adapter_available: true, capabilities_known: true,
  provider: "test", model: "img", kind: "image", capabilities: {},
} as GenerationOption;

it("框里删空过(留着一份空文档)再连上便签:框里显示便签的字,提交的也是它", async () => {
  const onSubmit = vi.fn();
  const item = {
    id: "image", kind: "image",
    form: { prompt: "", prompt_document: { type: "doc", content: [{ type: "paragraph" }] } },
  } as unknown as BoardItem;
  const props = { item, models: [model], busy: false, workspaceId: "w", onPickAsset: vi.fn(), onFormChange: vi.fn(), onSubmit };
  const view = render(<NodeComposer {...props} upstreamTexts={[]} />);
  view.rerender(<NodeComposer {...props} upstreamTexts={[{ itemId: "n1", text: "一只橘猫趴在窗台上" }]} />);

  await waitFor(() => expect(document.querySelector(".ProseMirror")?.textContent).toBe("一只橘猫趴在窗台上"));
  fireEvent.click(screen.getByRole("button", { name: "boardGenerate" }));
  expect(onSubmit).toHaveBeenCalledWith(expect.objectContaining({ prompt: "一只橘猫趴在窗台上" }));
});
