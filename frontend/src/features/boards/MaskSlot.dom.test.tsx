/** @vitest-environment jsdom */
import { fireEvent, render, screen } from "@testing-library/react";
import React from "react";
import { describe, expect, it, vi } from "vitest";

vi.mock("@/app/preferences", () => ({ useI18n: () => (key: string) => key }));
vi.mock("@/components/app/image-preview", () => ({ useImagePreview: () => ({ openImagePreview: vi.fn() }) }));
//: 编辑器本身(画布、笔刷)有它自己的测试;这里只看蒙版槽开它时给了什么、存好之后怎么落。
const editor = vi.hoisted(() => ({ last: null as null | { open: boolean; source: unknown; initial: unknown; onDone: (asset: { id: string }) => void } }));
vi.mock("@/components/generation/MaskEditor", () => ({
  MaskEditor: (props: { open: boolean; source: unknown; initial: unknown; onDone: (asset: { id: string }) => void }) => {
    editor.last = props;
    return props.open ? <div data-testid="mask-editor" /> : null;
  },
}));

import { MaskSlot } from "./MaskSlot";

function mount(extra: Partial<React.ComponentProps<typeof MaskSlot>> = {}) {
  const handlers = { onPickLibrary: vi.fn(), onUseCandidate: vi.fn(), onSaved: vi.fn(), onRemove: vi.fn() };
  render(
    <MaskSlot
      label={(index) => `蒙版 ${index + 1}`}
      masks={[]}
      limit={1}
      candidates={[{ assetId: "up-1", itemId: "img-1" }, { assetId: "up-2", itemId: "img-2" }]}
      base={{ assetId: "ref", name: "参考图" }}
      workspaceId="w"
      drop={(button) => button}
      {...handlers}
      {...extra}
    />,
  );
  return handlers;
}

describe("画板的蒙版槽", () => {
  it("「+」里三种填法:画一张、用连进来的哪一张、从素材库挑", () => {
    const handlers = mount();
    fireEvent.click(screen.getByRole("button", { name: "蒙版 1" }));
    expect(screen.getByRole("menuitem", { name: /maskDraw/ })).toBeTruthy();
    expect(screen.getAllByRole("menuitem", { name: /boardMaskFromUpstream/ })).toHaveLength(2);

    fireEvent.click(screen.getAllByRole("menuitem", { name: /boardMaskFromUpstream/ })[1]);
    expect(handlers.onUseCandidate).toHaveBeenCalledWith({ assetId: "up-2", itemId: "img-2" });
  });

  it("画一张:编辑器的底图是这一格的参考图,存好的那张新加进蒙版槽", () => {
    const handlers = mount();
    fireEvent.click(screen.getByRole("button", { name: "蒙版 1" }));
    fireEvent.click(screen.getByRole("menuitem", { name: /maskDraw/ }));
    expect(screen.getByTestId("mask-editor")).toBeTruthy();
    expect(editor.last?.source).toEqual({ assetId: "ref", name: "参考图" });
    expect(editor.last?.initial).toBeNull();
    React.act(() => editor.last!.onDone({ id: "new-mask" }));
    expect(handlers.onSaved).toHaveBeenCalledWith("new-mask", undefined);
  });

  it("已经在槽里的那张:点它是接着画(底稿是它),存好的替换它;满了就没有「+」", () => {
    const handlers = mount({ masks: [{ assetId: "old-mask" }] });
    expect(screen.queryByRole("button", { name: "蒙版 2" })).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "maskEdit" }));
    expect(editor.last?.initial).toEqual({ assetId: "old-mask", name: "蒙版 1" });
    React.act(() => editor.last!.onDone({ id: "edited" }));
    expect(handlers.onSaved).toHaveBeenCalledWith("edited", "old-mask");
  });
});
