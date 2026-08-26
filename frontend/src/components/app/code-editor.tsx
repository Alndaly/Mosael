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
    language: "python" | "json";
    minHeight?: number;
    maxHeight?: number;
    placeholder?: string;
    /** 关掉行号/折叠槽:小 JSON 配置块用,单行时不至于挂个孤零零的行号。 */
    gutter?: boolean;
    onBlur?: () => void;
  }
>(function CodeEditor(
  { value, onChange, language, minHeight = 96, maxHeight = 320, placeholder, gutter = true, onBlur },
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
      className="h-fit overflow-hidden rounded-md border border-input focus-within:border-primary [&_.cm-editor]:rounded-md [&_.cm-editor]:font-mono [&_.cm-editor]:text-xs [&_.cm-editor.cm-focused]:outline-none [&_.cm-gutters]:border-0 [&_.cm-scroller]:font-mono [&_.cm-content]:min-h-[var(--cm-min-h)] [&_.cm-scroller]:min-h-[var(--cm-min-h)] [&_.cm-foldGutter_.cm-gutterElement]:flex [&_.cm-foldGutter_.cm-gutterElement]:items-center [&_.cm-foldGutter_.cm-gutterElement]:justify-center"
      style={{ "--cm-min-h": `${minHeight}px` } as React.CSSProperties}
    >
      <CodeMirror
        ref={cmRef}
        value={value}
        onChange={onChange}
        onBlur={onBlur}
        theme={dark ? "dark" : "light"}
        placeholder={placeholder}
        minHeight={`${minHeight}px`}
        maxHeight={`${maxHeight}px`}
        extensions={language === "python" ? [python()] : [json()]}
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
