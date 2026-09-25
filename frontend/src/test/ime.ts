import { act, fireEvent } from "@testing-library/react";

/**
 * 在 jsdom 里走一遍输入法组词(拼音为例),事件顺序照 Chromium / Electron:
 *
 *   compositionstart
 *   每个字母:keydown(isComposing, keyCode 229)→ 浏览器改 DOM → compositionupdate → input(isComposing)
 *   选词上屏:浏览器把拼音换成汉字 → input(isComposing)→ compositionend → keyup
 *
 * 「浏览器改 DOM」用原型上的 setter 直接写,**不经过 React** —— 真机上组词中的字就是浏览器
 * 自己放进去的。`steps` 是每一步之后框里的**整段**字(已有的字 + 组词中的拼音)。
 */
export function composeWithIme(field: HTMLInputElement | HTMLTextAreaElement, steps: string[], committed: string) {
  const setNative = nativeValueSetter(field);
  const letters = steps.map((step, index) => step.slice(index === 0 ? 0 : steps[index - 1]!.length).slice(-1));
  act(() => {
    field.focus();
    fireEvent.compositionStart(field, { data: "" });
  });
  steps.forEach((step, index) => {
    act(() => {
      field.dispatchEvent(new KeyboardEvent("keydown", { key: letters[index], isComposing: true, keyCode: 229, bubbles: true, cancelable: true }));
      setNative(step);
      fireEvent.compositionUpdate(field, { data: step });
      field.dispatchEvent(new InputEvent("input", { data: letters[index], inputType: "insertCompositionText", isComposing: true, bubbles: true }));
    });
  });
  act(() => {
    setNative(committed);
    field.dispatchEvent(new InputEvent("input", { data: committed, inputType: "insertCompositionText", isComposing: true, bubbles: true }));
    fireEvent.compositionEnd(field, { data: committed });
    field.dispatchEvent(new KeyboardEvent("keyup", { key: "Enter", keyCode: 229, bubbles: true }));
  });
}

/** 记下**别人**(React)往这个框的 value 写过什么。浏览器那一侧(composeWithIme)不算在内。 */
export function watchValueWrites(field: HTMLInputElement | HTMLTextAreaElement): string[] {
  const writes: string[] = [];
  const proto = Object.getPrototypeOf(field) as object;
  const descriptor = Object.getOwnPropertyDescriptor(proto, "value")!;
  Object.defineProperty(field, "value", {
    configurable: true,
    get() {
      return descriptor.get!.call(this);
    },
    set(next: string) {
      writes.push(next);
      descriptor.set!.call(this, next);
    },
  });
  return writes;
}

function nativeValueSetter(field: HTMLInputElement | HTMLTextAreaElement) {
  const descriptor = Object.getOwnPropertyDescriptor(Object.getPrototypeOf(field) as object, "value")!;
  return (next: string) => descriptor.set!.call(field, next);
}
