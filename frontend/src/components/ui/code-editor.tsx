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
    onBlur?: () => void;
  }
>(function CodeEditor({ value, onChange, language, minHeight = 96, maxHeight = 320, placeholder, onBlur }, ref) {
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
    <div className="code-editor">
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
          lineNumbers: true,
          foldGutter: true,
          highlightActiveLine: false,
          autocompletion: false,
          highlightActiveLineGutter: false,
        }}
      />
    </div>
  );
});
