import React from "react";
import CodeBlock from "@tiptap/extension-code-block";
import { NodeViewContent, NodeViewWrapper, ReactNodeViewRenderer, type NodeViewProps } from "@tiptap/react";
import { Plugin, PluginKey } from "@tiptap/pm/state";
import { Decoration, DecorationSet } from "@tiptap/pm/view";
import { Check, Copy } from "lucide-react";
import { canonicalLanguage, codeHighlighter } from "@/components/agent/codeHighlighter";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { NONE, optionalValue } from "@/components/ui/selectSentinel";
import { nodeLabels } from "./noteNodeUI";

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
    /**
     * 围栏要比正文里最长的那串反引号更长。
     *
     * 上游写死了三个反引号(extension-code-block 的 renderMarkdown),于是**一段讲 Markdown 的
     * 代码块会把自己拆掉**:```` ```md ```` 里包着 ``` ```js ``` 时,内层那行提前把块收尾了,
     * 剩下的内容掉到正文里变成普通段落 —— 而且再存一次形状还会继续变(实测两遍不收敛)。
     * CommonMark 对这件事有明确规定,照它办即可。
     *
     * 这在这个应用里不是边角情况:笔记里写技术文档、或者把模型回答里的代码示例存成笔记,
     * 一段带 ``` 的内容就够了。
     */
    renderMarkdown(node, h) {
      const language = String(node.attrs?.language || "");
      const body = node.content ? h.renderChildren(node.content) : "";
      const longest = Math.max(0, ...Array.from(String(body).matchAll(/`+/g), (m) => m[0].length));
      const fence = "`".repeat(Math.max(3, longest + 1));
      return `${fence}${language}\n${body}\n${fence}`;
    },
    addProseMirrorPlugins() {
      return [...(this.parent?.() || []), syntaxHighlighting()];
    },
    addNodeView() {
      return ReactNodeViewRenderer(CodeBlockView(labels));
    },
  });
}

/**
 * 代码块的头部:语言选择器、复制按钮,和 ProseMirror 自己管的那块代码正文。
 *
 * 此前这一块是手写 DOM,语言用的是原生 `<select>` —— 展开是系统菜单,和应用里别处的下拉长得
 * 不是一回事,收起时又没有背景,看不出是个能点的控件。换成仓库自己的 Select。
 */
function CodeBlockView(labels: ReturnType<typeof nodeLabels>) {
  return function View({ node, editor, getPos, updateAttributes }: NodeViewProps) {
    const [status, setStatus] = React.useState("");
    const timer = React.useRef<ReturnType<typeof setTimeout>>(undefined);
    React.useEffect(() => () => clearTimeout(timer.current), []);

    const stored = String(node.attrs.language || "");
    // ```shell 存下来就是 shell,而选项值是 bash —— 同一种语言,别在列表末尾再补一个。
    const value = canonicalLanguage(stored) || stored;
    const known = LANGUAGES.some(([id]) => id === value);
    const label = LANGUAGES.find(([id]) => id === value)?.[1] || value || labels.plain;

    const copy = async () => {
      try {
        await navigator.clipboard.writeText(node.textContent);
        setStatus(labels.copied);
      } catch {
        setStatus(labels.failed);
      }
      clearTimeout(timer.current);
      timer.current = setTimeout(() => setStatus(""), 1800);
    };

    return (
      <NodeViewWrapper className="note-code-block">
        <div className="note-code-header" contentEditable={false}>
          {editor.isEditable ? (
            <Select value={value || NONE} onValueChange={(next) => updateAttributes({ language: optionalValue(next) })}>
              <SelectTrigger className="note-code-language" aria-label={labels.language}>
                <SelectValue placeholder={labels.plain} />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value={NONE}>{labels.plain}</SelectItem>
                {!known && value && <SelectItem value={value}>{value}</SelectItem>}
                {LANGUAGES.map(([id, name]) => <SelectItem key={id} value={id}>{name}</SelectItem>)}
              </SelectContent>
            </Select>
          ) : (
            <span className="note-code-language-label">{label}</span>
          )}
          <span className="note-code-status" role="status">{status}</span>
          <button
            type="button"
            className="note-node-button"
            title={labels.copy}
            aria-label={labels.copy}
            onClick={() => void copy()}
          >
            {status === labels.copied ? <Check size={15} aria-hidden="true" /> : <Copy size={15} aria-hidden="true" />}
          </button>
        </div>
        <pre
          spellCheck={false}
          // 先把光标落到点下去的位置,再等下一个按键。否则被选中的图片会一直是模型里的选区,
          // 直到浏览器那边的 selectionchange 姗姗来迟。
          onMouseDown={(event) => {
            if (!editor.isEditable || event.button !== 0 || event.shiftKey || event.detail > 1) return;
            const hit = editor.view.posAtCoords({ left: event.clientX, top: event.clientY });
            const pos = getPos();
            if (hit && typeof pos === "number" && hit.pos > pos && hit.pos < pos + node.nodeSize) {
              editor.commands.setTextSelection(hit.pos);
            }
          }}
        >
          <NodeViewContent<"code"> as="code" className={value ? `language-${value}` : ""} />
        </pre>
      </NodeViewWrapper>
    );
  };
}
