import React from "react";
// 只从**已声明的包**里取:@tiptap/react 再导出了 core,StarterKit 里已含 Document/Paragraph/
// Text/History。不额外添依赖 —— 单个扩展包全都能从这两个里拿到。
import {
  EditorContent,
  Node,
  NodeViewWrapper,
  ReactNodeViewRenderer,
  mergeAttributes,
  useEditor,
} from "@tiptap/react";
import StarterKit from "@tiptap/starter-kit";
import Placeholder from "@tiptap/extension-placeholder";

import { cn } from "@/lib/utils";
import { docToString, parsePieces, piecesToDoc } from "@/features/workflows/refDoc";

/**
 * 一段可以夹着**上游引用**的文本。
 *
 * 引用在这里是一个**原子标签**:整体选中、整体删除,退格不会把 `{{llm-1.text}}` 咬掉半截变成
 * `{{llm-1.tex`(那是纯 textarea 时代最烦人的一点 —— 半截引用在运行前看不出错,运行时才发作)。
 *
 * ## 为什么用 TipTap 而不是自己写 contenteditable
 *
 * 这是**中文优先**的应用,而输入法是这类编辑器最容易翻车的地方:composition 期间的 DOM 变更、
 * 光标落在原子节点边界上时的合成、以及合成中途撤销 —— ProseMirror 都已经处理对了。撤销栈、
 * 粘贴净化同理。自己写省下的是依赖体积,赔上的是"中文输入偶尔吞字"这种没法测又没法解释的毛病。
 *
 * 代价照实记:真用起来给包体加约 100KB(此前 tiptap 虽在 package.json 里,但全项目没人 import,
 * 所以是被 tree-shake 掉的)。
 *
 * ## 存的还是字符串
 *
 * 落库的永远是 `{{node.output}}` —— 后端插值引擎认的就是它,不能因为换了编辑器就变。
 * 字符串 ↔ 文档那一步是纯函数,单独测(见 refDoc.test)。
 */

/** 引用节点:行内、原子。`atom: true` 是关键 —— 没有它光标能走进标签内部,退格就咬半截。 */
const RefNode = Node.create({
  name: "ref",
  group: "inline",
  inline: true,
  atom: true,
  selectable: true,
  addAttributes: () => ({ ref: { default: "" } }),
  parseHTML: () => [{ tag: "span[data-ref]" }],
  renderHTML: ({ HTMLAttributes }: { HTMLAttributes: Record<string, unknown> }) => [
    "span",
    mergeAttributes(HTMLAttributes, { "data-ref": "" }),
  ],
  addNodeView: () => ReactNodeViewRenderer(RefChip),
});

function RefChip(props: { node: { attrs: { ref?: string } } }) {
  return (
    <NodeViewWrapper as="span" className="inline-block align-baseline">
      <span
        className="mx-px inline-flex items-center rounded-md bg-[color-mix(in_srgb,var(--primary)_14%,transparent)] px-1 py-px font-mono text-ui-2xs text-primary"
        // 整体选中时给个明确的高亮 —— 用户要看得出"我选中的是一整个引用",而不是几个字符。
        data-ref-chip=""
      >
        {props.node.attrs.ref}
      </span>
    </NodeViewWrapper>
  );
}

export function RefEditor({
  value,
  onChange,
  variables,
  placeholder,
  rows = 2,
  className,
}: {
  value: string;
  onChange: (next: string) => void;
  /** 上游能引用的输出,形如 `{{llm-1.text}}`。 */
  variables: string[];
  placeholder?: string;
  rows?: number;
  className?: string;
}) {
  //: 最后一次自己发出去的值。外面改了(撤销、智能体改图)才回灌,否则每敲一个字都会被
  //: prop 回流重建文档,光标跳到开头。
  const emitted = React.useRef(value);

  const editor = useEditor({
    extensions: [
      // 这些字段是**一段文本**,不是文档:标题、列表、引用块之类一概关掉,免得用户不小心
      // 敲出一个二级标题存进配置里。
      StarterKit.configure({
        heading: false,
        bulletList: false,
        orderedList: false,
        listItem: false,
        blockquote: false,
        codeBlock: false,
        horizontalRule: false,
        bold: false,
        italic: false,
        strike: false,
        code: false,
      }),
      RefNode,
      Placeholder.configure({ placeholder: placeholder ?? "" }),
    ],
    content: piecesToDoc(parsePieces(value)),
    editorProps: {
      attributes: {
        // nodrag / nowheel:这东西活在画布上,不挂的话在里面选文字会变成拖画布。
        class: cn(
          "nodrag nowheel w-full rounded-md border border-border bg-panel px-2 py-1.5 text-ui-sm leading-[1.6] text-foreground outline-none focus:border-primary",
          className,
        ),
        style: `min-height:${rows * 22 + 12}px`,
      },
    },
    onUpdate: ({ editor: instance }) => {
      const next = docToString(instance.getJSON());
      emitted.current = next;
      onChange(next);
    },
  });

  React.useEffect(() => {
    if (!editor || value === emitted.current) return;
    emitted.current = value;
    editor.commands.setContent(piecesToDoc(parsePieces(value)), { emitUpdate: false });
  }, [value, editor]);

  /** 把一个引用插到光标处。上游 chip 点一下走这里。 */
  const insert = (ref: string) => {
    if (!editor) return;
    editor
      .chain()
      .focus()
      .insertContent({ type: "ref", attrs: { ref: ref.replace(/^\{\{|\}\}$/g, "") } })
      .run();
  };

  return (
    <div className="grid gap-1">
      <EditorContent editor={editor} />
      {variables.length > 0 && (
        // 上游有什么直接摆出来,点一下插到光标处 —— 不用记 `{{}}` 怎么写,也不用回画布上看
        // 输出变量叫什么。
        <div className="flex flex-wrap gap-1">
          {variables.map((ref) => (
            <button
              key={ref}
              type="button"
              className="cursor-pointer rounded-md border-0 bg-[color-mix(in_srgb,var(--primary)_12%,transparent)] px-1.5 py-0.5 font-mono text-ui-2xs text-primary transition-colors hover:bg-[color-mix(in_srgb,var(--primary)_20%,transparent)]"
              onClick={() => insert(ref)}
            >
              {ref.replace(/^\{\{|\}\}$/g, "")}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
