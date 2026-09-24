import * as React from "react";
import { ChevronDown, Clock } from "lucide-react";

import { useI18n } from "@/app/preferences";
import { FIELD_TRIGGER_CHEVRON, FIELD_TRIGGER_CLASS } from "@/components/ui/field-trigger";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { cn } from "@/lib/utils";

const pad = (n: number) => String(n).padStart(2, "0");
const HOURS = Array.from({ length: 24 }, (_, i) => i);
const MINUTES = Array.from({ length: 60 }, (_, i) => i);

/** "HH:MM" → [时, 分]。读不出来的一律当 00:00 —— 这是展示,不是校验。 */
function split(value: string): [number, number] {
  const m = /^(\d{1,2}):(\d{2})/.exec(value);
  if (!m) return [0, 0];
  return [Math.min(23, Number(m[1])), Math.min(59, Number(m[2]))];
}

/**
 * 「一天里的某个时刻」选择器,值是 `HH:MM`。
 *
 * **不用 `<input type="time">`。** 原生控件的外观由浏览器决定:框的内距、字号、右侧那枚时钟
 * 图标都不吃表单的样式,和同一行的下拉框摆在一起高矮、底色、圆角都对不上;点开是 Chromium
 * 自带的蓝色拨盘,和应用里其它浮层不是一套东西。
 *
 * 这里触发器和 Select **共用 FIELD_TRIGGER_CLASS** —— 并排时看不出是两种控件;弹层是两列
 * 可滚动的「时 / 分」,选中态、悬停与菜单项同一套写法。选了分钟就收起(那是最后一步),
 * 选小时不收(通常接着要选分钟)。上下方向键在当前列里挪一格。
 *
 * 用在 Dialog 里时弹层要滚动,所以 Popover 恒带 `modal`(见 popover.tsx 顶部那段说明)。
 */
export function TimePicker({
  value,
  onChange,
  ariaLabel,
  className,
  disabled,
}: {
  value: string;
  onChange: (next: string) => void;
  ariaLabel?: string;
  className?: string;
  disabled?: boolean;
}) {
  const t = useI18n();
  const [open, setOpen] = React.useState(false);
  const [hour, minute] = split(value);
  const set = (h: number, m: number) => onChange(`${pad(h)}:${pad(m)}`);
  return (
    <Popover open={open} onOpenChange={setOpen} modal>
      <PopoverTrigger asChild>
        <button
          type="button"
          aria-label={ariaLabel}
          disabled={disabled}
          className={cn(FIELD_TRIGGER_CLASS, "tabular-nums", className)}
        >
          <Clock className="size-3.5 shrink-0 text-muted-foreground" aria-hidden="true" />
          <span>{`${pad(hour)}:${pad(minute)}`}</span>
          <ChevronDown className={FIELD_TRIGGER_CHEVRON} aria-hidden="true" />
        </button>
      </PopoverTrigger>
      <PopoverContent align="end" className="flex w-auto gap-1 p-1.5">
        <Column
          label={t("timePickerHour")}
          values={HOURS}
          selected={hour}
          onPick={(h) => set(h, minute)}
        />
        <span className="my-1 w-px shrink-0 bg-divider" aria-hidden="true" />
        <Column
          label={t("timePickerMinute")}
          values={MINUTES}
          selected={minute}
          onPick={(m, done) => {
            set(hour, m);
            if (done) setOpen(false);
          }}
        />
      </PopoverContent>
    </Popover>
  );
}

function Column({
  label,
  values,
  selected,
  onPick,
}: {
  label: string;
  values: number[];
  selected: number;
  /** `done`:这一下是点选(收起),不是方向键挪格(不收)。 */
  onPick: (value: number, done: boolean) => void;
}) {
  const list = React.useRef<HTMLDivElement>(null);
  // 打开时和用方向键挪格后,让选中那一项停在列的中间 —— 否则 23 点、59 分得自己往下翻。
  React.useLayoutEffect(() => {
    const item = list.current?.querySelector<HTMLElement>("[aria-selected=true]");
    item?.scrollIntoView?.({ block: "center" });
  }, [selected]);
  return (
    <div className="grid w-16 grid-cols-[minmax(0,1fr)] grid-rows-[auto_minmax(0,1fr)] gap-1">
      <span className="px-2 pt-1 text-center text-ui-2xs font-medium text-muted-foreground">{label}</span>
      <div
        ref={list}
        role="listbox"
        aria-label={label}
        tabIndex={0}
        className="grid max-h-56 gap-0.5 overflow-y-auto overscroll-contain rounded-md outline-none [scrollbar-width:none] focus-visible:ring-2 focus-visible:ring-ring"
        onKeyDown={(event) => {
          const step = event.key === "ArrowDown" ? 1 : event.key === "ArrowUp" ? -1 : 0;
          if (step) {
            event.preventDefault();
            onPick(values[(values.indexOf(selected) + step + values.length) % values.length], false);
          } else if (event.key === "Enter") {
            event.preventDefault();
            onPick(selected, true);
          }
        }}
      >
        {values.map((v) => (
          <button
            key={v}
            type="button"
            role="option"
            aria-selected={v === selected}
            tabIndex={-1}
            onClick={() => onPick(v, true)}
            className={cn(
              "h-8 shrink-0 rounded-md text-center text-ui-sm tabular-nums transition-colors hover:bg-secondary",
              v === selected && "bg-primary/10 font-medium text-primary hover:bg-primary/15",
            )}
          >
            {pad(v)}
          </button>
        ))}
      </div>
    </div>
  );
}
