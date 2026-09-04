/** @vitest-environment jsdom */
import React from "react";
import { cleanup, render, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";

vi.mock("@/app/preferences", () => ({ useI18n: () => (key: string) => key }));

import { BoardCommentComposer, collectMentionedUserIds } from "./BoardCommentComposer";

afterEach(cleanup);
beforeAll(() => {
  document.elementFromPoint = () => document.body;
  Range.prototype.getClientRects = () => [] as unknown as DOMRectList;
  Range.prototype.getBoundingClientRect = () => new DOMRect();
});

describe("画布评论编辑器", () => {
  it("从 Tiptap 文档保留真实成员 ID，而不是依赖显示名猜测", () => {
    expect(collectMentionedUserIds({
      type: "doc",
      content: [{
        type: "paragraph",
        content: [
          { type: "userMention", attrs: { userId: "user-2", label: "小林" } },
          { type: "text", text: " 看这里" },
          { type: "userMention", attrs: { userId: "user-2", label: "小林" } },
        ],
      }],
    })).toEqual(["user-2"]);
  });

  it("点击评论正文时聚焦编辑器且不会把按下事件交给画布", async () => {
    const user = userEvent.setup();
    const onCanvasPointerDown = vi.fn();
    const view = render(
      <div onPointerDown={onCanvasPointerDown}>
        <BoardCommentComposer
          members={[]}
          onSubmit={vi.fn()}
          onCancel={vi.fn()}
        />
      </div>,
    );
    const editor = await waitFor(() =>
      view.container.querySelector<HTMLElement>("[contenteditable='true']"),
    );
    expect(editor).toBeTruthy();

    await user.click(editor as HTMLElement);

    expect(editor).toHaveFocus();
    expect(onCanvasPointerDown).not.toHaveBeenCalled();
  });

  it("提交结构化正文与纯文本摘要", async () => {
    const onSubmit = vi.fn().mockResolvedValue(undefined);
    const view = render(
      <BoardCommentComposer
        members={[]}
        onSubmit={onSubmit}
        onCancel={vi.fn()}
      />,
    );
    const editor = await waitFor(() => view.container.querySelector<HTMLElement>("[contenteditable='true']"));
    expect(editor).toBeTruthy();
    await userEvent.type(editor as HTMLElement, "请看构图");
    await userEvent.click(view.getByRole("button", { name: "send" }));

    await waitFor(() => expect(onSubmit).toHaveBeenCalledTimes(1));
    expect(onSubmit.mock.calls[0][0].body).toBe("请看构图");
    expect(onSubmit.mock.calls[0][0].bodyDocument.type).toBe("doc");
  });
});
