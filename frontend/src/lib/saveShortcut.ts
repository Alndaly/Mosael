import React from "react";

import { comboFromEvent, listenKeys } from "@/lib/shortcuts";

/**
 * ⌘S / Ctrl+S:全应用一个行为 —— **这一页能存就马上存,不能存也不让浏览器弹「存储网页」**。
 *
 * 此前只有工作流画布认 ⌘S,而且焦点在检查器的字段里时它也让路;笔记、画板、3D 场景都靠自动保存,
 * 没人接这个键。网页版里习惯性一按,弹出来的是浏览器的「存储网页」对话框;桌面版菜单里没有 ⌘S,
 * 按了什么都不发生 —— 同一个键在相邻两页上意思不一样。
 *
 * 做法:main.tsx 装一个全局监听(`installSaveShortcut`),任何焦点下都 `preventDefault`;页面用
 * `useSaveShortcut(fn)` 登记「此刻按 ⌘S 存什么」(自动保存的页面就是立刻把欠着的那份存掉)。
 * 后登记的先接 —— 更晚挂上的那一层(打开着的编辑器)比底下的列表更近。
 *
 * **输入框、编辑器里一样接。** 在笔记正文、检查器字段里按 ⌘S,想的就是存这一页,而不是浏览器的另存为。
 *
 * ComfyUI 工作台在捕获阶段先接住落在它自己那一栏里的 ⌘S(存那张工作流、不往下传),这里听的是冒泡阶段,
 * 两者不会同时存。
 */
type Saver = { save: () => void };
const savers: Saver[] = [];
let installed: (() => void) | null = null;

/** 和 ComfyUI 工作台的保存键同一个判据(`Mod+S`,先认物理键):⇧⌘S、⌥⌘S 不算。 */
export function isSaveChord(event: Pick<KeyboardEvent, "key" | "code" | "metaKey" | "ctrlKey" | "altKey" | "shiftKey">): boolean {
  return comboFromEvent(event) === "Mod+S";
}

export function handleSaveShortcut(event: KeyboardEvent): void {
  if (!isSaveChord(event)) return;
  event.preventDefault();
  savers[savers.length - 1]?.save();
}

/** 装一次全局监听;重复装(热更新)不叠第二个。返回拆掉它的函数。 */
export function installSaveShortcut(target: Window = window): () => void {
  if (installed) return installed;
  const remove = listenKeys(target, handleSaveShortcut);
  installed = () => {
    remove();
    installed = null;
  };
  return installed;
}

/** 登记「此刻按 ⌘S 存什么」。传 null 表示这一页现在没有可存的(键照样被拦下)。 */
export function useSaveShortcut(save: (() => void) | null | undefined): void {
  const ref = React.useRef(save);
  ref.current = save;
  React.useEffect(() => {
    const entry: Saver = { save: () => ref.current?.() };
    savers.push(entry);
    return () => {
      const index = savers.indexOf(entry);
      if (index >= 0) savers.splice(index, 1);
    };
  }, []);
}
