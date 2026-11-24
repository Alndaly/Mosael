/**
 * 打光节点(`image_relight`,ADR 0108)那几个数和方向球的几何。控件见 LightRigField。
 *
 * 灯位相对**画面**:方位 0 = 从镜头这边(顺光)、90 = 画面右侧、180 = 背后(逆光)、270 = 左侧;高度 0 = 与视线齐平、
 * 90 = 正顶光。和后端 executors/relight 同一套约定、同一份缺省 —— 那边把这几个数翻成交给模型的话,这里只摆和拖。
 */
import type { MessageKey } from "@/app/messages";

export interface Light {
  azimuth: number;
  elevation: number;
  temperature: number;
  softness: number;
  intensity: number;
}

/** 节点上存这几个数的那几格(和后端 NODE_TYPES 的 image_relight 同名)。 */
export const LIGHT_KEYS: Record<keyof Light, string> = {
  azimuth: "light_azimuth",
  elevation: "light_elevation",
  temperature: "light_temperature",
  softness: "light_softness",
  intensity: "light_intensity",
};

/** 缺省和后端 relight.DEFAULTS 同一份:左前方、斜上方 45°、日光、不软不硬、亮度适中。 */
export const DEFAULT_LIGHT: Light = { azimuth: 315, elevation: 45, temperature: 5500, softness: 0.5, intensity: 60 };

export const LIGHT_RANGES = {
  temperature: { min: 1500, max: 12000, step: 100 },
  softness: { min: 0, max: 1, step: 0.05 },
  intensity: { min: 0, max: 100, step: 1 },
} as const;

/** 从节点配置里读出这几个数:没写、写错的用缺省,超出的夹到边上(和后端 light_values 同一条规矩)。 */
export function readLight(config: Record<string, unknown>): Light {
  const read = (key: keyof Light): number => {
    const value = Number(config[LIGHT_KEYS[key]]);
    return Number.isFinite(value) && config[LIGHT_KEYS[key]] !== "" && config[LIGHT_KEYS[key]] != null ? value : DEFAULT_LIGHT[key];
  };
  return {
    azimuth: ((read("azimuth") % 360) + 360) % 360,
    elevation: clamp(read("elevation"), 0, 90),
    temperature: clamp(read("temperature"), LIGHT_RANGES.temperature.min, LIGHT_RANGES.temperature.max),
    softness: clamp(read("softness"), LIGHT_RANGES.softness.min, LIGHT_RANGES.softness.max),
    intensity: clamp(read("intensity"), LIGHT_RANGES.intensity.min, LIGHT_RANGES.intensity.max),
  };
}

/** 改了几个数 → 写回节点的那一份(只写改了的那几格)。 */
export function lightPatch(change: Partial<Light>): Record<string, number> {
  return Object.fromEntries(
    (Object.entries(change) as [keyof Light, number][]).map(([key, value]) => [LIGHT_KEYS[key], Math.round(value * 100) / 100]),
  );
}

function clamp(value: number, low: number, high: number): number {
  return Math.min(Math.max(value, low), high);
}

/** 方向球往下看的角度:略俯视,方位环看成一个椭圆,前后分得清。 */
const TILT = (20 * Math.PI) / 180;

/**
 * 方位 / 高度 → 方向球上那颗光点的位置(以球心为原点、半径 1 的平面坐标,y 向下)和它在前面还是后面(`front`,
 * 用来把转到背后的光点画暗一点)。
 */
export function orbPoint(azimuth: number, elevation: number): { x: number; y: number; front: boolean } {
  const az = (azimuth * Math.PI) / 180;
  const el = (elevation * Math.PI) / 180;
  const x = Math.sin(az) * Math.cos(el);
  const up = Math.sin(el);
  //: 朝镜头那边(方位 0)为正。
  const toward = Math.cos(az) * Math.cos(el);
  return { x, y: -(up * Math.cos(TILT) - toward * Math.sin(TILT)), front: toward >= 0 };
}

/** 方向键微调:左右转方位(往右,光往画面右边走),上下改高度(往上,光升高)。高度夹在 0–90,方位绕圈。 */
export function nudgeLight(light: Pick<Light, "azimuth" | "elevation">, azimuthStep: number, elevationStep: number) {
  return {
    azimuth: (((light.azimuth + azimuthStep) % 360) + 360) % 360,
    elevation: clamp(light.elevation + elevationStep, 0, 90),
  };
}

/**
 * 方位把手:指针在方位环那个平面上的位置(相对球心、以半径为 1,y 向下)→ 方位。方位环是地平线那一圈俯视看成的
 * 椭圆(见 orbPoint):x = sin(方位),y = cos(方位)·sin(俯视角)—— 反过来求角度。指针在环里环外都按方向算。
 */
export function azimuthFromPoint(x: number, y: number): number {
  const degrees = (Math.atan2(x, y / Math.sin(TILT)) * 180) / Math.PI;
  return ((degrees % 360) + 360) % 360;
}

/**
 * 高度把手:指针相对球心的位置 → 高度。高度弧是球左边那四分之一圈(从左边的地平线升到头顶),和画面平行,
 * 按指针在左上那个象限里的角度算:贴着地平线是 0,正上方是 90。
 */
export function elevationFromPoint(x: number, y: number): number {
  const degrees = (Math.atan2(-y, -x) * 180) / Math.PI;
  return clamp(degrees, 0, 90);
}

/** 高度弧上把手的位置(相对球心、半径 1):左边地平线是 0,正上方是 90。 */
export function elevationHandle(elevation: number): { x: number; y: number } {
  const angle = (elevation * Math.PI) / 180;
  return { x: -Math.cos(angle), y: -Math.sin(angle) };
}

/** 方位落在哪个方向(八个方向,和后端翻指令时的分法一样):给方向球下面那行字。 */
export function directionKey(azimuth: number): MessageKey {
  const index = Math.round((((azimuth % 360) + 360) % 360) / 45) % 8;
  return DIRECTION_KEYS[index];
}

const DIRECTION_KEYS: MessageKey[] = [
  "lightDirFront", "lightDirFrontRight", "lightDirRight", "lightDirBackRight",
  "lightDirBack", "lightDirBackLeft", "lightDirLeft", "lightDirFrontLeft",
];

/** 一键摆好的几种常见打光。**只是摆数**,不进数据:选了之后再拖,就是自己的那一套。 */
export const LIGHT_PRESETS: { id: string; label: MessageKey; light: Light }[] = [
  { id: "rembrandt", label: "lightPresetRembrandt", light: { azimuth: 315, elevation: 45, temperature: 4800, softness: 0.35, intensity: 55 } },
  { id: "window", label: "lightPresetWindow", light: { azimuth: 270, elevation: 20, temperature: 6000, softness: 0.8, intensity: 60 } },
  { id: "rim", label: "lightPresetRim", light: { azimuth: 180, elevation: 25, temperature: 5600, softness: 0.3, intensity: 45 } },
  { id: "top", label: "lightPresetTop", light: { azimuth: 0, elevation: 85, temperature: 5500, softness: 0.25, intensity: 50 } },
  { id: "golden", label: "lightPresetGolden", light: { azimuth: 300, elevation: 8, temperature: 3000, softness: 0.6, intensity: 65 } },
  { id: "overcast", label: "lightPresetOvercast", light: { azimuth: 0, elevation: 70, temperature: 7000, softness: 0.95, intensity: 55 } },
];

/** 现在这一套正好是哪一种预设(四舍五入后对得上);对不上是 null。 */
export function matchingPreset(light: Light): string | null {
  const same = (a: number, b: number) => Math.abs(a - b) < 0.01;
  return (
    LIGHT_PRESETS.find((one) => (Object.keys(one.light) as (keyof Light)[]).every((key) => same(one.light[key], light[key])))?.id ?? null
  );
}
