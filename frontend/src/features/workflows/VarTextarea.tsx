import React from "react";
import { cn } from "@/lib/utils";
import { Textarea } from "@/components/ui/textarea";

/**
 * 支持 Dify 式「/ 唤起变量弹窗」的 textarea:
 * 输入 `/` 在光标处弹出上游变量列表,继续输入过滤,↑↓ 选择、Enter/Tab 插入、Esc 关闭。
 *
 * 光标像素定位用镜像 div 技巧(textarea 拿不到光标坐标):把 textarea 的排版样式
 * 复制到一个隐藏 div,填入光标前的文本 + 一个标记 span,span 的 offset 即光标位置。
 */

const MIRROR_STYLES = [
  "boxSizing", "width", "paddingTop", "paddingRight", "paddingBottom", "paddingLeft",
  "borderTopWidth", "borderRightWidth", "borderBottomWidth", "borderLeftWidth",
  "fontFamily", "fontSize", "fontWeight", "fontStyle", "letterSpacing",
  "lineHeight", "textTransform", "wordSpacing", "whiteSpace", "wordBreak", "overflowWrap",
] as const;

function caretCoordinates(textarea: HTMLTextAreaElement, index: number): { top: number; left: number } {
  const mirror = document.createElement("div");
  const style = window.getComputedStyle(textarea);
  for (const key of MIRROR_STYLES) {
    mirror.style[key as "width"] = style[key as "width"];
  }
  mirror.style.position = "absolute";
  mirror.style.visibility = "hidden";
  mirror.style.whiteSpace = "pre-wrap";
  mirror.style.wordBreak = "break-word";
  document.body.appendChild(mirror);
  mirror.textContent = textarea.value.slice(0, index);
  const marker = document.createElement("span");
  marker.textContent = "​";
  mirror.appendChild(marker);
  const top = marker.offsetTop - textarea.scrollTop;
  const left = marker.offsetLeft - textarea.scrollLeft;
  mirror.remove();
  return { top, left };
}

/** 光标前最近的、以空白/行首开头的 `/token`;没有则 null。 */
function slashQueryAt(value: string, caret: number): { start: number; query: string } | null {
  const before = value.slice(0, caret);
  const slash = before.lastIndexOf("/");
  if (slash < 0) return null;
  if (slash > 0 && !/[\s({\[,:，:、]/.test(before[slash - 1])) return null;
  const query = before.slice(slash + 1);
  if (/[\s]/.test(query)) return null;
  return { start: slash, query };
}

export function VarTextarea({
  value,
  onChange,
  variables,
  rows,
  className,
  textareaRef,
}: {
  value: string;
  onChange: (next: string) => void;
  variables: string[];
  rows?: number;
  className?: string;
  textareaRef?: (el: HTMLTextAreaElement | null) => void;
}) {
  const innerRef = React.useRef<HTMLTextAreaElement | null>(null);
  const [menu, setMenu] = React.useState<{
    start: number;
    query: string;
    top: number;
    left: number;
    index: number;
  } | null>(null);

  const matches = React.useMemo(() => {
    if (!menu) return [];
    const query = menu.query.toLowerCase();
    return variables.filter((ref) => ref.toLowerCase().includes(query)).slice(0, 8);
  }, [menu, variables]);

  const sync = (el: HTMLTextAreaElement) => {
    if (variables.length === 0) return setMenu(null);
    const found = slashQueryAt(el.value, el.selectionStart ?? 0);
    if (!found) return setMenu(null);
    const pos = caretCoordinates(el, found.start);
    const lineHeight = Number.parseFloat(window.getComputedStyle(el).lineHeight) || 18;
    setMenu((current) => ({
      start: found.start,
      query: found.query,
      top: pos.top + lineHeight + 4,
      left: Math.max(0, Math.min(pos.left, el.clientWidth - 190)),
      index: current && current.start === found.start ? Math.min(current.index, 7) : 0,
    }));
  };

  const insert = (ref: string) => {
    const el = innerRef.current;
    if (!el || !menu) return;
    const caret = el.selectionStart ?? value.length;
    const next = value.slice(0, menu.start) + ref + value.slice(caret);
    onChange(next);
    setMenu(null);
    requestAnimationFrame(() => {
      el.focus();
      el.selectionStart = el.selectionEnd = menu.start + ref.length;
    });
  };

  return (
    <div className="relative [&_textarea]:w-full">
      <Textarea
        ref={(el) => {
          innerRef.current = el;
          textareaRef?.(el);
        }}
        rows={rows}
        className={className}
        value={value}
        onChange={(event) => {
          onChange(event.target.value);
          sync(event.target);
        }}
        onKeyDown={(event) => {
          if (!menu || matches.length === 0) return;
          if (event.key === "ArrowDown" || event.key === "ArrowUp") {
            event.preventDefault();
            const delta = event.key === "ArrowDown" ? 1 : -1;
            setMenu((current) =>
              current ? { ...current, index: (current.index + delta + matches.length) % matches.length } : current,
            );
          } else if (event.key === "Enter" || event.key === "Tab") {
            event.preventDefault();
            insert(matches[menu.index] ?? matches[0]);
          } else if (event.key === "Escape") {
            event.preventDefault();
            event.stopPropagation();
            setMenu(null);
          }
        }}
        onClick={(event) => sync(event.currentTarget)}
        onBlur={() => window.setTimeout(() => setMenu(null), 150)}
      />
      {menu && matches.length > 0 && (
        <div className="absolute z-40 flex min-w-[180px] max-w-[280px] flex-col rounded-md border border-border bg-panel p-[3px]" style={{ top: menu.top, left: menu.left }} role="listbox">
          {matches.map((ref, index) => (
            <button
              key={ref}
              type="button"
              role="option"
              aria-selected={index === menu.index}
              className={cn(
                "block cursor-pointer truncate rounded-md border-0 bg-transparent px-1.5 py-1 text-left font-mono text-[11px]",
                index === menu.index && "bg-[color-mix(in_srgb,var(--primary)_10%,transparent)] text-primary",
              )}
              onMouseDown={(event) => event.preventDefault()}
              onClick={() => insert(ref)}
              onMouseEnter={() => setMenu((current) => (current ? { ...current, index } : current))}
            >
              {ref.replace(/[{}]/g, "")}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
