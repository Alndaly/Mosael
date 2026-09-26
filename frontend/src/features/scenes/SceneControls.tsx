import React from "react";
import type { Vec3 } from "@/api/domains/scenes";
import type { FieldSize } from "@/components/ui/control-size";
import { OptionPicker } from "@/components/ui/option-picker";
import { isImeKeystroke } from "@/lib/shortcuts";
export function Pick({
  value,
  options,
  onChange,
  label,
  icon,
  size,
  className,
}: {
  value: string;
  options: [string, string][];
  onChange: (v: string) => void;
  label: string;
  icon?: React.ReactNode;
  /** 档位跟着所在那一行走(工具栏 xs、浮层里 sm),和同行的按钮同一把尺。 */
  size?: FieldSize;
  className?: string;
}) {
  // 物体/机位清单跟着场景走,一多就得能搜(阈值在 OptionPicker 里)。
  return (
    <OptionPicker
      value={value}
      onChange={onChange}
      options={options.map(([id, name]) => ({ value: id, label: name }))}
      ariaLabel={label}
      icon={icon}
      size={size}
      className={className}
    />
  );
}
export function Num({
  value,
  onChange,
  label,
  caption,
  min = -10000,
  max = 10000,
  step = 0.1,
}: {
  value: number;
  onChange: (n: number) => void;
  label: string;
  caption?: string;
  min?: number;
  max?: number;
  step?: number;
}) {
  const [text, setText] = React.useState(
    String(Math.round(value * 1000) / 1000),
  );
  React.useEffect(
    () => setText(String(Math.round(value * 1000) / 1000)),
    [value],
  );
  function commit() {
    const n = Number(text);
    if (text.trim() && Number.isFinite(n)) {
      const v = Math.max(min, Math.min(max, n));
      setText(String(v));
      if (v !== value) onChange(v);
    } else setText(String(value));
  }
  return (
    <label className="scene-number">
      <span>{caption ?? label}</span>
      <input
        type="number"
        aria-label={label}
        step={step}
        min={min}
        max={max}
        value={text}
        onChange={(e) => setText(e.target.value)}
        onBlur={commit}
        onKeyDown={(e) => {
          if (isImeKeystroke(e)) return;
          if (e.key === "Enter") {
            e.currentTarget.blur();
          }
        }}
      />
    </label>
  );
}
export function Vector({
  label,
  value,
  onChange,
  min,
  max,
}: {
  label: string;
  value: Vec3;
  onChange: (v: Vec3) => void;
  min?: number;
  max?: number;
}) {
  return (
    <div className="scene-field">
      <span>{label}</span>
      <div className="scene-vector">
        {value.map((v, i) => (
          <Num
            key={i}
            label={`${label} ${"XYZ"[i]}`}
            caption={"XYZ"[i]}
            value={v}
            min={min}
            max={max}
            onChange={(n) =>
              onChange(value.map((x, j) => (i === j ? n : x)) as Vec3)
            }
          />
        ))}
      </div>
    </div>
  );
}
export function Tool({
  label,
  children,
  onClick,
  active,
  disabled,
}: {
  label: string;
  children: React.ReactNode;
  onClick: () => void;
  active?: boolean;
  disabled?: boolean;
}) {
  return (
    <button
      type="button"
      className="scene-tool"
      title={label}
      aria-label={label}
      aria-pressed={active}
      disabled={disabled}
      onClick={onClick}
    >
      {children}
    </button>
  );
}
