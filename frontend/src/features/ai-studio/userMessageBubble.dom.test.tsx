/** @vitest-environment jsdom */
import React from "react";
import type { JSONContent } from "@tiptap/react";
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

vi.mock("@/api/client", () => ({
  assetFileUrl: (id: string) => `/file/${id}`,
  assetPreviewUrl: (id: string) => `/preview/${id}`,
  assetThumbnailUrl: (id: string) => `/thumb/${id}`,
  api: async () => ({}),
}));
vi.mock("@/app/preferences", () => ({ useI18n: () => (key: string) => key }));
vi.mock("@/components/app/image-preview", () => ({ useImagePreview: () => ({ openImagePreview: () => {} }) }));

import { UserMessageContent } from "./userMessage";

const doc = (...content: JSONContent[]): JSONContent => ({ type: "doc", content: [{ type: "paragraph", content }] });
const ref = (name: string): JSONContent => ({ type: "agentRef", attrs: { kind: "asset", refId: "a1", name } });
const text = (value: string): JSONContent => ({ type: "text", text: value });

describe("用户气泡", () => {
  it("有文档时把引用画成胶囊,而不是一串 @名字", () => {
    render(<UserMessageContent content="把 @运镜练习 改长一点" document={doc(text("把 "), ref("运镜练习"), text(" 改长一点"))} />);
    expect(screen.getByText("运镜练习")).toBeInTheDocument();
  });

  /**
   * 发出去的 content 后面还接着别的:笔记引用的 `@标题`、文本附件内联成的围栏块 ——
   * 它们是发送时拼上去的,不在编辑器文档里。只画文档的话,挂了三条笔记发出去,
   * 气泡里一点痕迹都没有,而用户明明看着它们被挂上去了。
   */
  it("文档之后接着画 content 里剩下的那截 —— 笔记引用不该凭空消失", () => {
    render(
      <UserMessageContent
        content={"帮我看看\n@第一条笔记 @第二条笔记"}
        document={doc(text("帮我看看"))}
      />,
    );
    expect(screen.getByText(/@第一条笔记 @第二条笔记/)).toBeInTheDocument();
  });

  it("没有多余的那截就不留一个空块", () => {
    const { container } = render(<UserMessageContent content="就这一句" document={doc(text("就这一句"))} />);
    expect(container.textContent).toBe("就这一句");
  });

  /** 对不上前缀时宁可不画尾巴 —— 把同一句话画两遍比少画一截更糟。 */
  it("content 和文档对不上时不重复渲染", () => {
    const { container } = render(<UserMessageContent content="完全不一样的一句" document={doc(text("文档里的话"))} />);
    expect(container.textContent).toBe("文档里的话");
  });

  it("没有文档的老消息照旧按纯文本渲染", () => {
    const { container } = render(<UserMessageContent content="老消息" />);
    expect(container.textContent).toBe("老消息");
  });
});
