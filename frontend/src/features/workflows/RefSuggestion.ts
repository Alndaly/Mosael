import { Extension } from "@tiptap/react";
import Suggestion, { type SuggestionOptions } from "@tiptap/suggestion";

/**
 * `@` 唤起上游引用的建议菜单 —— **一个 ProseMirror 插件,不是外挂在 React 上的状态**。
 *
 * 第一版是我自己写的:React state 记菜单、editorProps.handleKeyDown 接按键、
 * coordsAtPos 算位置。它能跑,但架构上是错的,而且错得有具体后果:
 *
 * **输入法。** handleKeyDown 没有(也很难周全地)处理 composition —— 中文选词时按回车,
 * 会被菜单当成"选中这一条"吃掉,候选词上不了屏。而我选 TipTap 的理由恰恰就是"IME 难写对",
 * 结果偏偏把 IME 真正咬人的那一段手写了。
 *
 * **状态放错了层。** 为了让创建时注册的 handleKeyDown 看见后来的菜单,得塞三个 ref
 * (菜单、编辑器、变量表)去对抗过期闭包。需要三个 ref 才能读到自己的状态,说明这份状态
 * 本来就该住在编辑器里。
 *
 * 官方 Suggestion 插件把这两件事都归位了:查询追踪和按键路由在插件里(它知道 composition),
 * 弹层的样子仍然归我们。分工是「编辑器管什么时候、管到哪个字符;React 管长什么样」。
 */
export const RefSuggestion = Extension.create<{
  suggestion: Omit<SuggestionOptions, "editor">;
}>({
  name: "refSuggestion",
  addOptions() {
    return { suggestion: { char: "@" } as Omit<SuggestionOptions, "editor"> };
  },
  addProseMirrorPlugins() {
    return [Suggestion({ editor: this.editor, ...this.options.suggestion })];
  },
});
