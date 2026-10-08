/** @vitest-environment jsdom */
/**
 * 能拖的那几处给读屏的说明和播报走界面语言。dnd-kit 不给就用它自带的英文,说明讲的是这几处根本没装的键盘拖法,
 * 播报念的是内部 id。
 */
import React from "react";
import { DndContext, useDraggable } from "@dnd-kit/core";
import { cleanup, render } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { messages } from "@/app/messages";
import { openTags, readSource, tsxSources } from "@/design/jsxSource";

vi.mock("@/app/preferences", () => ({
  useI18n: () => (key: keyof (typeof messages)["zh-CN"]) => messages["zh-CN"][key],
}));
import { useDndAccessibility } from "./dndAccessibility";

afterEach(cleanup);

function Item() {
  const { attributes, listeners, setNodeRef } = useDraggable({ id: "a1b2c3" });
  return <button ref={setNodeRef} {...attributes} {...listeners}>一项</button>;
}
function List() {
  return (
    <DndContext accessibility={useDndAccessibility()}>
      <Item />
    </DndContext>
  );
}

describe("拖动的读屏说明", () => {
  it("说明是界面语言的那句,不是 dnd-kit 自带的英文键盘说明", () => {
    render(<List />);
    const button = document.querySelector("button")!;
    const describedBy = button.getAttribute("aria-describedby")!;
    const text = document.getElementById(describedBy)?.textContent ?? "";
    expect(text).toBe(messages["zh-CN"].dndInstructions);
    expect(text).not.toMatch(/press space|draggable item/i);
  });

  it("播报不念内部 id", () => {
    function Probe({ onReady }: { onReady: (value: ReturnType<typeof useDndAccessibility>) => void }) {
      onReady(useDndAccessibility());
      return null;
    }
    let value: ReturnType<typeof useDndAccessibility> | null = null;
    render(<Probe onReady={(one) => (value = one)} />);
    const active = { id: "a1b2c3" } as never;
    const said = [
      value!.announcements.onDragStart({ active }),
      value!.announcements.onDragOver?.({ active, over: { id: "z9" } as never }),
      value!.announcements.onDragEnd({ active, over: null }),
      value!.announcements.onDragCancel({ active, over: null }),
    ];
    for (const one of said) expect(one).not.toContain("a1b2c3");
    expect(said[0]).toBe(messages["zh-CN"].dndPickedUp);
    expect(said[2]).toBe(messages["zh-CN"].dndCancelled);
  });

  it("每一个 <DndContext> 都给了 accessibility(要么用这一份,要么像表单搭建器那样自己接键盘、自己念)", () => {
    const missing = tsxSources().flatMap((file) =>
      openTags(readSource(file))
        .filter((tag) => tag.tag === "DndContext" && !tag.attrs.has("accessibility"))
        .map((tag) => `${file}:${tag.line}`),
    );
    expect(missing).toEqual([]);
  });
});
