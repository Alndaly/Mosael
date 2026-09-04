/** @vitest-environment jsdom */
import React from "react";
import { cleanup, fireEvent, render } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("@/app/preferences", () => ({ useI18n: () => (key: string) => key }));

import { BoardCommentModeHint } from "./BoardCanvas";

afterEach(cleanup);

describe("画布评论模式提示", () => {
  it("只通过独立关闭按钮退出，点击说明不会退出或穿透画布", () => {
    const onExit = vi.fn();
    const onCanvasClick = vi.fn();
    const view = render(
      <div onClick={onCanvasClick}>
        <BoardCommentModeHint onExit={onExit} />
      </div>,
    );

    fireEvent.click(view.getByText("boardCommentModeHint"));
    expect(onExit).not.toHaveBeenCalled();
    expect(onCanvasClick).not.toHaveBeenCalled();

    fireEvent.click(view.getByRole("button", { name: "boardExitCommentMode" }));
    expect(onExit).toHaveBeenCalledTimes(1);
    expect(onCanvasClick).not.toHaveBeenCalled();
  });
});
