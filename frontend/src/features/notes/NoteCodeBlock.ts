import CodeBlock from "@tiptap/extension-code-block";
import { Plugin, PluginKey } from "@tiptap/pm/state";
import { Decoration, DecorationSet } from "@tiptap/pm/view";
import { codeHighlighter } from "@/components/agent/codeHighlighter";
import { nodeButton, nodeIcon, nodeLabels } from "./noteNodeUI";

type Highlight = NonNullable<ReturnType<typeof codeHighlighter.highlight>>;
const highlightKey = new PluginKey<DecorationSet>("note-code-highlight");
function highlight(code: string, language: string): Promise<Highlight | null> {
  if (!codeHighlighter.supportsLanguage(language) || code.length > 50000)
    return Promise.resolve(null);
  return new Promise((resolve) => {
    const result = codeHighlighter.highlight(
      { code, language, themes: codeHighlighter.getThemes() },
      resolve,
    );
    if (result) resolve(result);
  });
}
// Decorations color ProseMirror's own text, preserving native editing, IME and selection.
function syntaxHighlighting() {
  return new Plugin<DecorationSet>({
    key: highlightKey,
    state: {
      init: () => DecorationSet.empty,
      apply: (tr, previous) =>
        tr.getMeta(highlightKey) ?? previous.map(tr.mapping, tr.doc),
    },
    props: { decorations: (state) => highlightKey.getState(state) },
    view(view) {
      let destroyed = false;
      let timer: ReturnType<typeof setTimeout>;
      const cache = new Map<string, Promise<Highlight | null>>();
      function schedule() {
        clearTimeout(timer);
        timer = setTimeout(() => {
          if (view.composing) { schedule(); return; }
          const doc = view.state.doc;
          const blocks: Promise<Decoration[]>[] = [];
          doc.descendants((node, pos) => {
            if (node.type.name !== "codeBlock") return;
            const code = node.textContent,
              language = String(node.attrs.language || "");
            const key = `${language}\0${code}`;
            let tokens = cache.get(key);
            if (!tokens) {
              tokens = highlight(code, language);
              cache.set(key, tokens);
            }
            blocks.push(
              tokens.then((result) => {
                const spans: Decoration[] = [];
                let offset = pos + 1;
                result?.tokens.forEach((line) => {
                  line.forEach((token) => {
                    const end = offset + token.content.length;
                    if (end > offset) {
                      const light = token.htmlStyle?.color || token.color;
                      const dark = token.htmlStyle?.["--shiki-dark"] || light;
                      spans.push(
                        Decoration.inline(offset, end, {
                          class: "note-code-token",
                          style: `--note-code-light:${light || "inherit"};--note-code-dark:${dark || "inherit"}`,
                        }),
                      );
                    }
                    offset = end;
                  });
                  offset += 1;
                });
                return spans;
              }),
            );
          });
          if (cache.size > 64) cache.clear();
          void Promise.all(blocks).then((spans) => {
            if (!destroyed && view.state.doc === doc) {
              view.dispatch(
                view.state.tr
                  .setMeta(
                    highlightKey,
                    DecorationSet.create(doc, spans.flat()),
                  )
                  .setMeta("addToHistory", false),
              );
            }
          });
        }, 100);
      }
      schedule();
      return {
        update(next, previous) {
          if (next.state.doc !== previous.doc) schedule();
        },
        destroy() {
          destroyed = true;
          clearTimeout(timer);
          cache.clear();
        },
      };
    },
  });
}
const LANGUAGES: [string, string][] = [
  ["javascript", "JavaScript"],
  ["typescript", "TypeScript"],
  ["tsx", "TSX"],
  ["python", "Python"],
  ["html", "HTML"],
  ["css", "CSS"],
  ["json", "JSON"],
  ["bash", "Shell"],
  ["sql", "SQL"],
  ["yaml", "YAML"],
  ["markdown", "Markdown"],
  ["diff", "Diff"],
];
export function createNoteCodeBlock(locale: string) {
  const labels = nodeLabels(locale);
  return CodeBlock.extend({
    addProseMirrorPlugins() {
      return [...(this.parent?.() || []), syntaxHighlighting()];
    },
    addNodeView() {
      return ({ node: initial, editor, getPos }) => {
        let node = initial,
          destroyed = false;
        let copiedTimer: ReturnType<typeof setTimeout>;
        const dom = document.createElement("div");
        dom.className = "note-code-block";
        const header = document.createElement("div");
        header.className = "note-code-header";
        header.contentEditable = "false";
        const language = document.createElement("select");
        language.className = "note-code-language";
        language.setAttribute("aria-label", labels.language);
        for (const [value, label] of [["", labels.plain], ...LANGUAGES]) {
          language.add(new Option(label, value));
        }
        const label = document.createElement("span");
        label.className = "note-code-language-label";
        const status = document.createElement("span");
        status.className = "note-code-status";
        status.setAttribute("role", "status");
        const copy = nodeButton(labels.copy, "copy");
        const pre = document.createElement("pre"),
          contentDOM = document.createElement("code");
        pre.spellcheck = false;
        pre.append(contentDOM);
        header.append(language, label, status, copy);
        dom.append(header, pre);
        function render() {
          const value = String(node.attrs.language || "");
          for (const option of Array.from(language.options))
            if (option.dataset.custom) option.remove();
          if (
            value &&
            !Array.from(language.options).some(
              (option) => option.value === value,
            )
          ) {
            const custom = new Option(value, value);
            custom.dataset.custom = "true";
            language.add(custom);
          }
          language.value = value;
          language.hidden = !editor.isEditable;
          label.hidden = editor.isEditable;
          label.textContent = language.selectedOptions[0]?.text || labels.plain;
          const className = value ? `language-${value}` : "";
          if (contentDOM.className !== className)
            contentDOM.className = className;
        }
        // Commit the pointer position before the next key event. A selected image can
        // otherwise remain the model selection until the browser's selectionchange arrives.
        pre.onmousedown = (event) => {
          if (
            !editor.isEditable ||
            event.button !== 0 ||
            event.shiftKey ||
            event.detail > 1
          )
            return;
          const hit = editor.view.posAtCoords({
            left: event.clientX,
            top: event.clientY,
          });
          const pos = getPos();
          if (
            hit &&
            typeof pos === "number" &&
            hit.pos > pos &&
            hit.pos < pos + node.nodeSize
          ) {
            editor.commands.setTextSelection(hit.pos);
          }
        };
        language.onchange = () => {
          const pos = getPos();
          if (!editor.isEditable || typeof pos !== "number") return;
          editor.view.dispatch(
            editor.state.tr.setNodeMarkup(pos, undefined, {
              ...node.attrs,
              language: language.value || null,
            }),
          );
        };
        copy.onclick = async () => {
          try {
            await navigator.clipboard.writeText(node.textContent);
            if (destroyed) return;
            status.textContent = labels.copied;
            copy.replaceChildren(nodeIcon("check"));
            clearTimeout(copiedTimer);
            copiedTimer = setTimeout(() => {
              status.textContent = "";
              copy.replaceChildren(nodeIcon("copy"));
            }, 1800);
          } catch {
            if (!destroyed) status.textContent = labels.failed;
          }
        };
        render();
        return {
          dom,
          contentDOM,
          update(next) {
            if (next.type !== node.type) return false;
            node = next;
            render();
            return true;
          },
          stopEvent: (event) =>
            header.contains(event.target as globalThis.Node),
          ignoreMutation: (mutation) =>
            mutation.type !== "selection" &&
            !contentDOM.contains(mutation.target),
          destroy() {
            destroyed = true;
            clearTimeout(copiedTimer);
          },
        };
      };
    },
  });
}
