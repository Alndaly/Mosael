import React from "react";

import { useI18n } from "@/app/preferences";
import { Chip } from "@/components/ui/chip";
import { Slider } from "@/components/ui/slider";
import { Hint } from "@/components/ui/tooltip";
import {
  azimuthFromPoint,
  directionKey,
  elevationFromPoint,
  elevationHandle,
  LIGHT_PRESETS,
  LIGHT_RANGES,
  matchingPreset,
  nudgeLight,
  orbPoint,
  type Light,
} from "@/features/nodeForms/lightRig";

/** 方向球的画布(SVG 用户坐标)。宽扁的一块,铺满卡片的宽;CSS 按同一个宽高比放大,指针换算才是线性的。 */
const VIEW = { width: 240, height: 132 };
const CENTER = { x: 120, y: 80 };
/** 方位环、高度弧的半径。 */
const R = 64;
/** 方向键一下走几度。 */
const NUDGE = 5;

type Handle = "azimuth" | "elevation";

/**
 * 打光节点(`image_relight`,ADR 0108)的灯位:**一个控件改五格**(后端声明 `editor: "light_rig"`,另外四格 `edited_by` 它)。
 * 工作流检查器、画板的能力面板(摆在面板主体里,见 stageEditors)用的是同一个控件。
 *
 * 方向球**两个把手各管一件事,拿着走**:方位环(绕着人那一圈)上的把手管光从哪个方向来,左边那四分之一弧上的把手管
 * 光多高;点环或弧也直接跳到那里。光点只显示光现在在哪(转到人背后时画暗),不能拖 —— 此前是「在球上任意拖,按位移
 * 转方位和高度」,光点转到背面以后往右拖它反而往左走,手和光点对不上(维护者:「交互很怪异」)。方向键微调。
 *
 * 下面是一排常用打光(只是一键摆好这几个数)和色温、软硬、亮度三个滑杆,都铺满卡片的宽。
 */
export function LightRigField({ light, onChange }: { light: Light; onChange: (change: Partial<Light>) => void }) {
  const t = useI18n();
  const svg = React.useRef<SVGSVGElement>(null);
  const [held, setHeld] = React.useState<Handle | null>(null);
  const readout = t("lightRigReadout")
    .replace("{direction}", t(directionKey(light.azimuth)))
    .replace("{azimuth}", String(Math.round(light.azimuth)))
    .replace("{elevation}", String(Math.round(light.elevation)));
  const preset = matchingPreset(light);

  const dot = orbPoint(light.azimuth, light.elevation);
  const dotAt = at(dot);
  const azimuthAt = at(orbPoint(light.azimuth, 0));
  const elevationAt = at(elevationHandle(light.elevation));
  const subject = { x: CENTER.x, y: CENTER.y - 6 };

  /** 指针 → 相对球心、以半径为 1 的坐标(y 向下)。画布按 viewBox 的宽高比放大,所以是线性换算。 */
  const local = (event: React.PointerEvent): { x: number; y: number } | null => {
    const box = svg.current?.getBoundingClientRect();
    if (!box || !box.width || !box.height) return null;
    return {
      x: (((event.clientX - box.left) / box.width) * VIEW.width - CENTER.x) / R,
      y: (((event.clientY - box.top) / box.height) * VIEW.height - CENTER.y) / R,
    };
  };
  const follow = (handle: Handle, event: React.PointerEvent) => {
    const point = local(event);
    if (!point) return;
    onChange(handle === "azimuth" ? { azimuth: azimuthFromPoint(point.x, point.y) } : { elevation: elevationFromPoint(point.x, point.y) });
  };
  const grab = (handle: Handle) => (event: React.PointerEvent) => {
    event.stopPropagation();
    svg.current?.setPointerCapture(event.pointerId);
    setHeld(handle);
    follow(handle, event);
  };
  const onKeyDown = (event: React.KeyboardEvent<SVGSVGElement>) => {
    const step: Record<string, [number, number]> = {
      ArrowLeft: [-NUDGE, 0], ArrowRight: [NUDGE, 0], ArrowUp: [0, NUDGE], ArrowDown: [0, -NUDGE],
    };
    const move = step[event.key];
    if (!move) return;
    event.preventDefault();
    onChange(nudgeLight(light, move[0], move[1]));
  };

  return (
    <div className="grid gap-3" data-light-rig="">
      <Hint label={t("lightRigHint")}>
        <div className="relative w-full overflow-hidden rounded-md bg-secondary">
          <svg
            ref={svg}
            role="group"
            tabIndex={0}
            aria-label={`${t("lightRigLabel")}: ${readout}`}
            aria-description={t("lightRigHint")}
            viewBox={`0 0 ${VIEW.width} ${VIEW.height}`}
            className="nodrag block aspect-[240/132] w-full touch-none outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring"
            onPointerMove={(event) => held && follow(held, event)}
            onPointerUp={() => setHeld(null)}
            onPointerCancel={() => setHeld(null)}
            onKeyDown={onKeyDown}
          >
            {/* 方位环:光绕着人转的那一圈(略俯视,看成椭圆)。粗的那层是看不见的点击区,点环就跳到那个方向。 */}
            <ellipse cx={CENTER.x} cy={CENTER.y} rx={R} ry={R * orbPoint(0, 0).y} fill="none" stroke="var(--border-strong)" />
            <ellipse data-light-ring="azimuth" cx={CENTER.x} cy={CENTER.y} rx={R} ry={R * orbPoint(0, 0).y} fill="none"
              stroke="transparent" strokeWidth={14} className="cursor-pointer" onPointerDown={grab("azimuth")} />
            {/* 高度弧:左边那四分之一圈,从地平线升到头顶。 */}
            <path d={heightArc()} fill="none" stroke="var(--border-strong)" />
            <path data-light-ring="elevation" d={heightArc()} fill="none" stroke="transparent" strokeWidth={14}
              className="cursor-pointer" onPointerDown={grab("elevation")} />
            {/* 被照的那个人,和照向他的那束光。光的颜色由光点自己说;线用界面的次要色,日光色的线在浅色底上看不见。 */}
            <circle cx={subject.x} cy={subject.y} r={10} fill="var(--muted-foreground)" opacity={0.45} />
            <line x1={dotAt.x} y1={dotAt.y} x2={subject.x} y2={subject.y} stroke="var(--muted-foreground)" strokeDasharray="3 2" />
            <circle cx={dotAt.x} cy={dotAt.y} r={7} fill={kelvinColor(light.temperature)} stroke="var(--foreground)"
              strokeWidth={1} opacity={dot.front ? 1 : 0.5} pointerEvents="none" />
            {/* 两个把手。 */}
            <circle data-light-handle="azimuth" cx={azimuthAt.x} cy={azimuthAt.y} r={6} fill="var(--primary)" stroke="var(--background)"
              strokeWidth={2} className={held === "azimuth" ? "cursor-grabbing" : "cursor-grab"} onPointerDown={grab("azimuth")} />
            <circle data-light-handle="elevation" cx={elevationAt.x} cy={elevationAt.y} r={6} fill="var(--primary)"
              stroke="var(--background)" strokeWidth={2} className={held === "elevation" ? "cursor-grabbing" : "cursor-grab"}
              onPointerDown={grab("elevation")} />
          </svg>
          <span className="pointer-events-none absolute bottom-2 left-2 text-ui-xs text-foreground">{readout}</span>
        </div>
      </Hint>
      <div className="flex flex-wrap gap-1" role="group" aria-label={t("lightPresets")}>
        {LIGHT_PRESETS.map((one) => (
          <Chip key={one.id} selected={preset === one.id} onClick={() => onChange(one.light)}>
            {t(one.label)}
          </Chip>
        ))}
      </div>
      <div className="grid grid-cols-[auto_minmax(0,1fr)_auto] items-center gap-x-2 gap-y-2">
        <SliderRow label={t("lightTemperature")} value={light.temperature} range={LIGHT_RANGES.temperature}
          shown={`${Math.round(light.temperature)}K`} onChange={(temperature) => onChange({ temperature })} />
        <SliderRow label={t("lightSoftness")} value={light.softness} range={LIGHT_RANGES.softness}
          shown={`${Math.round(light.softness * 100)}%`} onChange={(softness) => onChange({ softness })} />
        <SliderRow label={t("lightIntensity")} value={light.intensity} range={LIGHT_RANGES.intensity}
          shown={String(Math.round(light.intensity))} onChange={(intensity) => onChange({ intensity })} />
      </div>
    </div>
  );
}

/** 相对球心、以半径为 1 的坐标 → 画布上的点。 */
function at(point: { x: number; y: number }): { x: number; y: number } {
  return { x: CENTER.x + point.x * R, y: CENTER.y + point.y * R };
}

/** 高度弧:左边地平线(0°)到头顶(90°)的四分之一圈。 */
function heightArc(): string {
  const start = at(elevationHandle(0));
  const end = at(elevationHandle(90));
  return `M${start.x},${start.y} A${R},${R} 0 0 1 ${end.x},${end.y}`;
}

function SliderRow({ label, value, range, shown, onChange }: {
  label: string;
  value: number;
  range: { min: number; max: number; step: number };
  shown: string;
  onChange: (value: number) => void;
}) {
  return (
    <>
      <span className="text-ui-xs text-muted-foreground">{label}</span>
      <Slider aria-label={label} className="nodrag" min={range.min} max={range.max} step={range.step} value={[value]}
        onValueChange={([next]) => onChange(next)} />
      <span className="min-w-10 text-right text-ui-xs tabular-nums text-muted-foreground">{shown}</span>
    </>
  );
}

/** 色温 → 光点的颜色(近似:低色温偏橙、日光近白、高色温偏蓝)。这是光的颜色,是数据,不是界面配色。 */
export function kelvinColor(kelvin: number): string {
  const stops: [number, [number, number, number]][] = [
    [1500, [255, 138, 40]], [3200, [255, 190, 120]], [5500, [255, 244, 229]], [7500, [214, 228, 255]], [12000, [160, 190, 255]],
  ];
  const upper = stops.findIndex(([threshold]) => kelvin <= threshold);
  if (upper <= 0) return rgb(stops[upper === 0 ? 0 : stops.length - 1][1]);
  const [lowAt, low] = stops[upper - 1];
  const [highAt, high] = stops[upper];
  const mix = (kelvin - lowAt) / (highAt - lowAt);
  return rgb([0, 1, 2].map((i) => Math.round(low[i] + (high[i] - low[i]) * mix)) as [number, number, number]);
}

function rgb([r, g, b]: [number, number, number]): string {
  return `rgb(${r}, ${g}, ${b})`;
}
