import { Extension } from "@tiptap/react";
import { Plugin, PluginKey } from "@tiptap/pm/state";
import { Decoration, DecorationSet } from "@tiptap/pm/view";

const focusKey = new PluginKey<boolean>("noteInactiveSelection");

/**
 * 编辑器失焦时**仍然画出选区**。
 *
 * 笔记页的助手读的是编辑器里的选区(见 noteSelection):选中一段、点进助手输入框打字,选区还在
 * 编辑器的状态里、会跟着消息发出去 —— 可浏览器的高亮跟着焦点走了,用户看不见「它会带上哪一段」。
 * 失焦时把那一段画成浅色底,发出去的是哪段一眼就知道。
 */
export const InactiveSelection = Extension.create({
  name: "noteInactiveSelection",
  addProseMirrorPlugins() {
    return [
      new Plugin<boolean>({
        key: focusKey,
        state: {
          init: () => false,
          apply: (tr, focused) => {
            const meta = tr.getMeta(focusKey);
            return typeof meta === "boolean" ? meta : focused;
          },
        },
        props: {
          handleDOMEvents: {
            focus: (view) => {
              view.dispatch(view.state.tr.setMeta(focusKey, true).setMeta("addToHistory", false));
              return false;
            },
            blur: (view) => {
              view.dispatch(view.state.tr.setMeta(focusKey, false).setMeta("addToHistory", false));
              return false;
            },
          },
          decorations: (state) => {
            const { from, to, empty } = state.selection;
            if (empty || focusKey.getState(state)) return null;
            return DecorationSet.create(state.doc, [Decoration.inline(from, to, { class: "note-inactive-selection" })]);
          },
        },
      }),
    ];
  },
});
