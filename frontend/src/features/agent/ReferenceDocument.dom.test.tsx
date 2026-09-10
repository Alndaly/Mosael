/** @vitest-environment jsdom */
import React from "react";
import type { JSONContent } from "@tiptap/react";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

vi.mock("@/api/client", () => ({
  assetThumbnailUrl: (id: string) => `/thumb/${id}`,
  assetFileUrl: (id: string) => `/file/${id}`,
}));
const openImagePreview = vi.fn();
vi.mock("@/components/app/image-preview", () => ({ useImagePreview: () => ({ openImagePreview }) }));

import { ReferenceDocument } from "./ReferenceDocument";
import { REFERENCE_NODE } from "./ReferenceChip";

/**
 * **发出去之后引用仍然是胶囊,不是一串字。**
 *
 * 此前聊天输入是 textarea,附件靠往正文里拼一段标记、发出去再用正则拆回来。那条路只对附件
 * 成立,而且中间那段字一旦被编辑过就散架。现在文档原样落库,气泡照它画 —— 发送这个动作
 * 本身不再把用户刚放进去的结构抹平。
 */
describe("用户消息里的引用", () => {
  it("画成胶囊,带得出 kind 和 id", () => {
    const document: JSONContent = {
      type: "doc",
      content: [
        {
          type: "paragraph",
          content: [
            { type: "text", text: "把 " },
            { type: REFERENCE_NODE, attrs: { kind: "workflow", refId: "w1", name: "口播整理" } },
            { type: "text", text: " 跑一遍" },
          ],
        },
      ],
    };
    const { container } = render(<ReferenceDocument document={document} />);
    expect(container.textContent).toContain("把");
    expect(container.textContent).toContain("跑一遍");
    const chip = container.querySelector("[data-agent-ref-kind]")!;
    expect(chip.getAttribute("data-agent-ref-kind")).toBe("workflow");
    expect(chip.getAttribute("data-agent-ref-id")).toBe("w1");
    expect(chip.textContent).toContain("口播整理");
  });

  it("认不出来的节点照文本渲染 —— 格式以后长出新节点时,老版本至少还读得出字", () => {
    const document: JSONContent = {
      type: "doc",
      content: [{ type: "paragraph", content: [{ type: "futureThing", text: "以后的东西" } as JSONContent] }],
    };
    render(<ReferenceDocument document={document} />);
    expect(screen.getByText("以后的东西")).toBeInTheDocument();
  });

  it("素材给缩略图,其余给图标 —— 素材是用样子认的", () => {
    const chipOf = (kind: string, id: string) => ({
      type: "doc",
      content: [{ type: "paragraph", content: [{ type: REFERENCE_NODE, attrs: { kind, refId: id, name: "x" } }] }],
    }) as JSONContent;
    const asset = render(<ReferenceDocument document={chipOf("asset", "a1")} />);
    expect(asset.container.querySelector("img")).toHaveAttribute("src", "/thumb/a1");
    asset.unmount();
    const note = render(<ReferenceDocument document={chipOf("note", "n1")} />);
    expect(note.container.querySelector("img")).toBeNull();
    expect(note.container.querySelector("svg")).toBeTruthy();
  });
});

/**
 * **点开看看** —— 输入框里和气泡里点起来该是同一个结果。用户刚亲手把它放进去,发出去之后
 * 点它什么都不发生,读起来像是发送把它变成了一张死图。
 */
describe("点开引用", () => {
  const bubble = (kind: string, id: string) =>
    ({
      type: "doc",
      content: [{ type: "paragraph", content: [{ type: REFERENCE_NODE, attrs: { kind, refId: id, name: "东西" } }] }],
    }) as JSONContent;

  it("素材走全局灯箱 —— 那里已经有翻页、Esc 和层级", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({ id: "a1", name: "图", kind: "image" }))));
    render(<ReferenceDocument document={bubble("asset", "a1")} />);
    await userEvent.click(screen.getByRole("button"));
    await vi.waitFor(() => expect(openImagePreview).toHaveBeenCalled());
  });

  it("笔记、画板、工作流是页面 —— 跳过去,不塞进一个只看得见开头的小弹层", async () => {
    for (const [kind, id, mark] of [["note", "n1", "note=n1"], ["board", "b1", "board=b1"], ["workflow", "w1", "workflow=w1"]] as const) {
      const view = render(<ReferenceDocument document={bubble(kind, id)} />);
      await userEvent.click(screen.getByRole("button"));
      expect(window.location.hash).toContain(mark);
      view.unmount();
    }
  });
});
