"use client";

import CodeMirror from "@uiw/react-codemirror";
import { json } from "@codemirror/lang-json";
import { useTheme } from "next-themes";

import { cn } from "@/lib/utils";

/** 管理台 JSON 编辑器：与应用内一样使用 CodeMirror 6，提供高亮、行号、括号匹配和折叠。 */
export function CodeEditor({
  value,
  onChange,
  className,
  minHeight = 224,
  maxHeight = 360,
}: {
  value: string;
  onChange: (value: string) => void;
  className?: string;
  minHeight?: number;
  maxHeight?: number;
}) {
  const { resolvedTheme } = useTheme();
  return (
    <div
      data-slot="code-editor"
      className={cn(
        "h-fit overflow-hidden rounded-md border border-input bg-transparent shadow-sm transition-shadow has-[.cm-focused]:border-primary has-[.cm-focused]:ring-4 has-[.cm-focused]:ring-primary/15 [&_.cm-editor]:bg-transparent! [&_.cm-editor]:font-mono [&_.cm-editor]:text-xs [&_.cm-editor.cm-focused]:outline-none! [&_.cm-gutters]:border-0! [&_.cm-gutters]:bg-transparent! [&_.cm-scroller]:font-mono [&_.cm-content]:min-h-[var(--cm-min-h)] [&_.cm-scroller]:min-h-[var(--cm-min-h)] [&_.cm-foldGutter_.cm-gutterElement]:flex [&_.cm-foldGutter_.cm-gutterElement]:items-center [&_.cm-foldGutter_.cm-gutterElement]:justify-center",
        className,
      )}
      style={{ "--cm-min-h": `${minHeight}px` } as React.CSSProperties}
    >
      <CodeMirror
        value={value}
        onChange={onChange}
        theme={resolvedTheme === "dark" ? "dark" : "light"}
        minHeight={`${minHeight}px`}
        maxHeight={`${maxHeight}px`}
        extensions={[json()]}
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
}
