/** @vitest-environment jsdom */
/**
 * ⌘C / ⌘X 什么时候归系统。
 *
 * 真机:在工作流的执行历史里选中一段输出、按 ⌘C,复制不下来 —— 画布把 ⌘C 接过去复制了
 * 还选着的节点,并且 preventDefault 掉了系统复制。剪辑器那边更彻底:⌘C 一律拿去复制片段。
 */
import { afterEach, describe, expect, it } from "vitest";

import { leaveClipboardToSystem } from "./shortcuts";

function press(target: EventTarget): KeyboardEvent {
  const event = new KeyboardEvent("keydown", { key: "c", metaKey: true, bubbles: true });
  Object.defineProperty(event, "target", { value: target });
  return event;
}

afterEach(() => {
  window.getSelection()?.removeAllRanges();
  document.body.innerHTML = "";
});

describe("⌘C 交给系统的时候", () => {
  it("焦点在输入框或可编辑区里", () => {
    const input = document.createElement("input");
    const editable = document.createElement("div");
    editable.setAttribute("contenteditable", "true"); // jsdom 不实现 contentEditable 的写入
    document.body.append(input, editable);
    expect(leaveClipboardToSystem(press(input))).toBe(true);
    expect(leaveClipboardToSystem(press(editable))).toBe(true);
  });

  it("页面上选中了一段文字 —— 哪怕焦点不在输入框里", () => {
    const output = document.createElement("pre");
    output.textContent = "https://mosael.oss-cn-shanghai.aliyuncs.com/a.png";
    document.body.append(output);
    const range = document.createRange();
    range.selectNodeContents(output);
    window.getSelection()?.addRange(range);

    expect(leaveClipboardToSystem(press(document.body))).toBe(true);
  });

  it("什么字都没选:画布 / 时间线照常接管,复制节点或片段", () => {
    expect(leaveClipboardToSystem(press(document.body))).toBe(false);
  });

  it("只选中了空白也不算", () => {
    const gap = document.createElement("div");
    gap.textContent = "   ";
    document.body.append(gap);
    const range = document.createRange();
    range.selectNodeContents(gap);
    window.getSelection()?.addRange(range);

    expect(leaveClipboardToSystem(press(document.body))).toBe(false);
  });
});
