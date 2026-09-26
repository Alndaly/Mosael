import React from "react";
import CodeMirror, { type ReactCodeMirrorRef } from "@uiw/react-codemirror";
import { python } from "@codemirror/lang-python";
import { json } from "@codemirror/lang-json";

/** 跟随应用主题(<html> 的 .dark 类)。 */
function useIsDark(): boolean {
  const [dark, setDark] = React.useState(() => document.documentElement.classList.contains("dark"));
  React.useEffect(() => {
    const update = () => setDark(document.documentElement.classList.contains("dark"));
    const observer = new MutationObserver(update);
    observer.observe(document.documentElement, { attributes: true, attributeFilter: ["class"] });
    return () => observer.disconnect();
  }, []);
  return dark;
}

const LANGUAGES: Record<string, () => ReturnType<typeof json>[]> = {
  python: () => [python()],
  json: () => [json()],
};

export interface CodeEditorHandle {
  /** 把文本插到光标处(变量 chip 用),无编辑器时追加到末尾。 */
  insertAtCursor: (text: string) => void;
}

/**
 * CodeMirror 6 代码输入框:语法高亮 / 行号 / 括号匹配 / 折叠,替代裸 textarea。
 * 受控(value/onChange)。可选 onBlur。ref 暴露插入方法给变量 chip。
 */
export const CodeEditor = React.forwardRef<
  CodeEditorHandle,
  {
    value: string;
    onChange: (value: string) => void;
    /** 高亮用哪种语言。认得的是 python / json,别的(插件配置里声明的 yaml、text……)照常编辑、不高亮。 */
    language: string;
    minHeight?: number;
    maxHeight?: number;
    placeholder?: string;
    /** 关掉行号/折叠槽:小 JSON 配置块用,单行时不至于挂个孤零零的行号。 */
    gutter?: boolean;
    onBlur?: () => void;
    /** 一打开就把光标放进去(弹窗里只有它一个要填的东西时)。 */
    autoFocus?: boolean;
    /**
     * 贴在编辑器顶边的一条工具栏(格式化、清空这类**作用于这段代码**的次要动作),和编辑器共用一个外框。
     *
     * 放这里而不是调用方的弹窗底部:那些动作放在「取消 / 保存」旁边,读起来像是弹窗的动作,
     * 而且和主按钮挤在一行分不清主次。工具栏里放 `size="xs"` 的按钮 —— 全应用工具栏的刻度。
     */
    toolbar?: React.ReactNode;
  }
>(function CodeEditor(
  { value, onChange, language, minHeight = 96, maxHeight = 320, placeholder, gutter = true, onBlur, autoFocus, toolbar },
  ref,
) {
  const dark = useIsDark();
  const cmRef = React.useRef<ReactCodeMirrorRef>(null);

  React.useImperativeHandle(
    ref,
    () => ({
      insertAtCursor: (text: string) => {
        const view = cmRef.current?.view;
        if (!view) {
          onChange(value + text);
          return;
        }
        const range = view.state.selection.main;
        view.dispatch({
          changes: { from: range.from, to: range.to, insert: text },
          selection: { anchor: range.from + text.length },
        });
        view.focus();
      },
    }),
    [value, onChange],
  );

  return (
    <div
      // 两件事一起保证"点哪都能聚焦":
      // 1) h-fit —— 外框收缩到编辑器实际高度,别被父级 grid/flex 的 align-stretch 拉高,否则
      //    editor 只有 minHeight、下方多出的空白是死区,点了不定位(表现为"除第一行外点击无效")。
      // 2) .cm-content/.cm-scroller 撑到 minHeight —— 内容仅一行时可点区也铺满到最小高度。
      // 3) 折叠箭头居中 —— CodeMirror 默认把 `›` 当**普通文字**放在槽里(display:inline,
      //    vertical-align:baseline),于是它按文字基线坐,而不是按行框居中,看着整体偏下。
      //    改成 flex 居中,箭头就落在行的正中。不给 leading-none —— 那会让裁切的文字被
      //    削掉顶和底(见 app/clippedText.test.ts 那道护栏),而 flex 居中本身已经够了。
      // 4) 底色和聚焦跟输入框(ui/input)走同一套 token:底是 bg-field、聚焦是 ring-2 ring-ring。
      //    CodeMirror 自带主题的底色(浅色 #fff、深色 one-dark 的 #282c34)是写死的,深色下是一块
      //    发蓝的灰,和应用的中性深色、弹窗里半透明的 --field 都不是一家;所以编辑器和行号槽一律透明,
      //    底色只由外框给。聚焦**只认编辑器本身**(.cm-focused),不用 focus-within —— 否则点一下
      //    工具栏上的按钮,整个编辑器也跟着亮起聚焦框。
      // 5) 改 CodeMirror 自己的样式一律带 `!`:它的样式是运行时注入的、**不在任何 layer 里**,
      //    而 Tailwind 的 utility 在 @layer utilities 里 —— 没进 layer 的样式不看特异性就赢。
      //    聚焦时的 `outline: 1px dotted` 就是这么漏出来的(外框的 ring 之外又多一圈虚线)。
      //    编辑器本身也不圆角:外框已经 overflow-hidden rounded-md,有工具栏时编辑器顶上再圆一次是错的。
      className="h-fit overflow-hidden rounded-md border border-field-border bg-field transition-shadow has-[.cm-focused]:ring-2 has-[.cm-focused]:ring-ring [&_.cm-editor]:bg-transparent! [&_.cm-gutters]:bg-transparent! [&_.cm-editor]:font-mono [&_.cm-editor]:text-xs [&_.cm-editor.cm-focused]:outline-none! [&_.cm-gutters]:border-0! [&_.cm-scroller]:font-mono [&_.cm-content]:min-h-[var(--cm-min-h)] [&_.cm-scroller]:min-h-[var(--cm-min-h)] [&_.cm-foldGutter_.cm-gutterElement]:flex [&_.cm-foldGutter_.cm-gutterElement]:items-center [&_.cm-foldGutter_.cm-gutterElement]:justify-center"
      style={{ "--cm-min-h": `${minHeight}px` } as React.CSSProperties}
    >
      {toolbar && (
        <div
          role="toolbar"
          data-slot="code-editor-toolbar"
          className="flex min-w-0 items-center gap-1 border-b border-field-border py-0.5 pl-2.5 pr-1"
        >
          {toolbar}
        </div>
      )}
      <CodeMirror
        ref={cmRef}
        value={value}
        onChange={onChange}
        onBlur={onBlur}
        autoFocus={autoFocus}
        theme={dark ? "dark" : "light"}
        placeholder={placeholder}
        minHeight={`${minHeight}px`}
        maxHeight={`${maxHeight}px`}
        extensions={LANGUAGES[language]?.() ?? []}
        basicSetup={{
          lineNumbers: gutter,
          foldGutter: gutter,
          highlightActiveLine: false,
          autocompletion: false,
          highlightActiveLineGutter: false,
        }}
      />
    </div>
  );
});
