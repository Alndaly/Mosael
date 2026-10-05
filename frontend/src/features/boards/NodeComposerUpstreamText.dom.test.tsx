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
vi.mock("@tanstack/react-query", () => ({
  useQuery: () => ({ data: [] }),
  //: 按 id 取引到的素材(useAssetDetails):一份都没取到。
  useQueries: ({ combine }: { combine: (results: unknown[]) => unknown }) => combine([]),
  useQueryClient: () => ({ invalidateQueries: vi.fn() }),
}));

afterEach(cleanup);

const model = {
  id: "m", provider_profile_id: "p", profile_name: "T", label: "L", adapter_available: true, is_default: true, capabilities_known: true,
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

it("连着文档:提交的只是框里写的那句,文档正文由服务端按连线交给模型", async () => {
  const onSubmit = vi.fn();
  const item = { id: "image", kind: "image", form: { prompt: "照这份脚本画第一幕" } } as unknown as BoardItem;
  const doc = { note_id: "n", revision: 2, title: "脚本", markdown: "# 第一幕\n\n清晨的码头", tags: [], citation_url: "#/notes?note=n&revision=2" };
  render(
    <NodeComposer
      item={item} models={[model]} busy={false} workspaceId="w" onPickAsset={vi.fn()} onFormChange={vi.fn()} onSubmit={onSubmit}
      upstreamTexts={[]} upstreamDocuments={[doc]}
    />,
  );

  await waitFor(() => expect(document.querySelector(".ProseMirror")?.textContent).toBe("照这份脚本画第一幕"));
  fireEvent.click(screen.getByRole("button", { name: "boardGenerate" }));
  expect(onSubmit).toHaveBeenCalledWith(expect.objectContaining({ prompt: "照这份脚本画第一幕" }));
  expect(screen.getByText(/脚本 · v2/)).toBeTruthy();
});

it("上游便签改了字,重新选中下游:自动填的那段跟着换;人改过的不动 —— 上次填了什么记在表单上,不在面板里", async () => {
  const onFormChange = vi.fn();
  //: 面板第一次挂上:便签的字填进来,表单记下填的是哪段。
  const first = { id: "image", kind: "image", form: { prompt: "" } } as unknown as BoardItem;
  const props = { models: [model], busy: false, workspaceId: "w", onPickAsset: vi.fn(), onSubmit: vi.fn() };
  render(<NodeComposer {...props} item={first} onFormChange={onFormChange} upstreamTexts={[{ itemId: "n1", text: "旧的那段" }]} />);
  await waitFor(() => expect(onFormChange).toHaveBeenLastCalledWith(expect.objectContaining({ prompt: "旧的那段", prefilled: "旧的那段" })));
  const stored = onFormChange.mock.calls.at(-1)![0];
  cleanup();

  //: 取消选中、改了上游便签的字、再选中:面板是新挂的,拿的是存下的表单。
  render(<NodeComposer {...props} item={{ ...first, form: stored }} onFormChange={vi.fn()} upstreamTexts={[{ itemId: "n1", text: "新的那段" }]} />);
  await waitFor(() => expect(document.querySelector(".ProseMirror")?.textContent).toBe("新的那段"));
  cleanup();

  render(<NodeComposer {...props} item={{ ...first, form: { ...stored, prompt: "我自己改的", prompt_document: undefined } }} onFormChange={vi.fn()}
                       upstreamTexts={[{ itemId: "n1", text: "新的那段" }]} />);
  await waitFor(() => expect(document.querySelector(".ProseMirror")?.textContent).toBe("我自己改的"));
});
