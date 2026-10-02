import React from "react";

/**
 * 颜色色块:**拖动只在本地预览,松手才提交一次**。
 *
 * React 的 `onChange` 在 `<input type="color">` 上跟的是原生 `input` 事件 —— 在取色器里拖一下就是
 * 几十次。此前每一次都直接写进片段 / 序列:几十条请求、几十步撤销历史,⌘Z 一次只退回一小格颜色。
 * 原生的 `change` 事件才是「选定了」(关掉取色器、松开)。所以:
 *  · `input`(React onChange)只改本地显示的颜色,并交给 `onPreview`(有实时预览的地方,如字幕样式);
 *  · 原生 `change` 提交一次;个别平台不发 change 时,失焦兜底提交;同一个值只提交一次。
 */
export function ColorSwatchInput({
  value,
  onCommit,
  onPreview,
  className,
  "aria-label": ariaLabel,
}: {
  value: string;
  onCommit: (value: string) => void;
  onPreview?: (value: string) => void;
  className?: string;
  "aria-label"?: string;
}) {
  const ref = React.useRef<HTMLInputElement | null>(null);
  // 拖动中的颜色。提交后先留着,等外面的 value 追上来再撤 —— 回包在途时色块不闪回旧色。
  const [draft, setDraft] = React.useState<string | null>(null);
  React.useEffect(() => setDraft(null), [value]);

  const latest = React.useRef({ value, onCommit, pending: false });
  latest.current.value = value;
  latest.current.onCommit = onCommit;

  const commit = React.useCallback((next: string) => {
    const state = latest.current;
    if (!state.pending) return;
    state.pending = false;
    if (next.toLowerCase() !== state.value.toLowerCase()) state.onCommit(next);
  }, []);

  React.useEffect(() => {
    const element = ref.current;
    if (!element) return;
    const onNativeChange = () => commit(element.value);
    element.addEventListener("change", onNativeChange);
    return () => element.removeEventListener("change", onNativeChange);
  }, [commit]);

  return (
    <input
      ref={ref}
      type="color"
      className={className}
      aria-label={ariaLabel}
      value={draft ?? value}
      onChange={(event) => {
        latest.current.pending = true;
        setDraft(event.target.value);
        onPreview?.(event.target.value);
      }}
      onBlur={(event) => commit(event.currentTarget.value)}
    />
  );
}
