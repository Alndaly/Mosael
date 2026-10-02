/** @vitest-environment jsdom */
import { afterEach, describe, expect, it } from "vitest";

import { isEditorKeyTarget } from "./editorKeys";

function editor(): { root: HTMLElement; add: (html: string) => HTMLElement } {
  const root = document.createElement("div");
  document.body.appendChild(root);
  return {
    root,
    add: (html) => {
      const holder = document.createElement("div");
      holder.innerHTML = html;
      const element = holder.firstElementChild as HTMLElement;
      root.appendChild(element);
      return element;
    },
  };
}

afterEach(() => {
  document.body.innerHTML = "";
});

describe("剪辑页快捷键的按键判定", () => {
  it("焦点在 body:都接", () => {
    const { root } = editor();
    expect(isEditorKeyTarget({ key: "Delete", target: document.body }, root)).toBe(true);
  });

  it("输入框里:都不接", () => {
    const { root, add } = editor();
    const input = add("<input />");
    expect(isEditorKeyTarget({ key: "s", target: input }, root)).toBe(false);
  });

  it("剪辑页外面(Portal 出去的菜单):都不接", () => {
    const { root } = editor();
    const menu = document.createElement("div");
    menu.setAttribute("role", "menu");
    document.body.appendChild(menu);
    expect(isEditorKeyTarget({ key: "Delete", target: menu }, root)).toBe(false);
    expect(isEditorKeyTarget({ key: "z", target: menu }, root)).toBe(false);
  });

  it("控件上:方向键、空格、Delete 让给控件,⌘Z / S 这类控件不用的键照常", () => {
    const { root, add } = editor();
    const slider = add('<span role="slider" tabindex="0"></span>');
    const button = add("<button>undo</button>");
    expect(isEditorKeyTarget({ key: "ArrowRight", target: slider }, root)).toBe(false);
    expect(isEditorKeyTarget({ key: " ", target: button }, root)).toBe(false);
    expect(isEditorKeyTarget({ key: "z", target: button }, root)).toBe(true);
    expect(isEditorKeyTarget({ key: "s", target: slider }, root)).toBe(true);
  });

  it("片段带 role=button 但它是画布元素:焦点在片段上一切照常", () => {
    const { root, add } = editor();
    const clip = add('<div role="button" tabindex="0" data-clip-id="c1"></div>');
    expect(isEditorKeyTarget({ key: "Delete", target: clip }, root)).toBe(true);
    expect(isEditorKeyTarget({ key: "ArrowLeft", target: clip }, root)).toBe(true);
  });
});
