/**
 * 打光预设。
 *
 * **每一档是两样东西的绑定**:一套灯位参数,和一段提示词片段。
 *
 * 灯位渲进参考帧,告诉模型光**从哪来**(影子是它最强的线索);文字告诉模型这是**什么光**
 * (暖的冷的、硬的柔的、什么场合)。只给图,模型不知道该往暖里走还是冷里走;只给词,
 * 光位又对不齐 —— 两样一起给才锁得住。同一场景的几个镜头用同一档,剪到一起才不穿帮。
 *
 * **按用途分组,不按布光术语分。** 用这一页的人想的是"我在拍一个产品",不是"我要一个
 * 45 度主光加 1:4 的补光比"。术语留在每一档的说明里给想深究的人看。
 */
import type { MessageKey } from "@/app/messages";
import type { SceneLighting } from "@/api/domains/scenes";

/** 文字一律是文案表的 key,按界面语言翻 —— 提示词也是:它会落进画板生成节点的提示词框,
 *  人要看、要改,英文界面里塞一段中文不合适。 */
export type LightingPreset = {
  id: string;
  group: MessageKey;
  label: MessageKey;
  /** 一句话说清它适合什么 —— 选择器里每一档下面那行。 */
  hint: MessageKey;
  /** 交给模型的那段话。**只描述光,不描述场景** —— 场景由参考帧和用户自己的提示词说。 */
  prompt: MessageKey;
  values: Omit<SceneLighting, "preset">;
};

const PRESETS: LightingPreset[] = [
  {
    id: "studio-soft",
    group: "sceneLightGroupProduct",
    label: "sceneLightStudioSoftLabel",
    hint: "sceneLightStudioSoftHint",
    prompt: "sceneLightStudioSoftPrompt",
    values: { azimuth: 35, elevation: 55, intensity: 2.5, temperature: 5500, softness: 0.7 },
  },
  {
    id: "product-crisp",
    group: "sceneLightGroupProduct",
    label: "sceneLightProductCrispLabel",
    hint: "sceneLightProductCrispHint",
    prompt: "sceneLightProductCrispPrompt",
    values: { azimuth: 55, elevation: 40, intensity: 4, temperature: 5200, softness: 0.08 },
  },
  {
    id: "desk-window",
    group: "sceneLightGroupProduct",
    label: "sceneLightDeskWindowLabel",
    hint: "sceneLightDeskWindowHint",
    prompt: "sceneLightDeskWindowPrompt",
    values: { azimuth: 80, elevation: 30, intensity: 2.8, temperature: 6000, softness: 0.55 },
  },
  {
    id: "portrait-soft",
    group: "sceneLightGroupPeople",
    label: "sceneLightPortraitSoftLabel",
    hint: "sceneLightPortraitSoftHint",
    prompt: "sceneLightPortraitSoftPrompt",
    values: { azimuth: 15, elevation: 45, intensity: 2.4, temperature: 5200, softness: 0.8 },
  },
  {
    id: "portrait-rim",
    group: "sceneLightGroupPeople",
    label: "sceneLightPortraitRimLabel",
    hint: "sceneLightPortraitRimHint",
    prompt: "sceneLightPortraitRimPrompt",
    values: { azimuth: 205, elevation: 35, intensity: 5, temperature: 6200, softness: 0.25 },
  },
  {
    id: "portrait-warm",
    group: "sceneLightGroupPeople",
    label: "sceneLightPortraitWarmLabel",
    hint: "sceneLightPortraitWarmHint",
    prompt: "sceneLightPortraitWarmPrompt",
    values: { azimuth: 50, elevation: 40, intensity: 2.2, temperature: 3200, softness: 0.65 },
  },
  {
    id: "noon-sun",
    group: "sceneLightGroupSpace",
    label: "sceneLightNoonSunLabel",
    hint: "sceneLightNoonSunHint",
    prompt: "sceneLightNoonSunPrompt",
    values: { azimuth: 20, elevation: 78, intensity: 4.5, temperature: 6000, softness: 0.12 },
  },
  {
    id: "golden-hour",
    group: "sceneLightGroupSpace",
    label: "sceneLightGoldenHourLabel",
    hint: "sceneLightGoldenHourHint",
    prompt: "sceneLightGoldenHourPrompt",
    values: { azimuth: 250, elevation: 12, intensity: 3.6, temperature: 3000, softness: 0.3 },
  },
  {
    id: "overcast",
    group: "sceneLightGroupSpace",
    label: "sceneLightOvercastLabel",
    hint: "sceneLightOvercastHint",
    prompt: "sceneLightOvercastPrompt",
    values: { azimuth: 0, elevation: 80, intensity: 1.6, temperature: 7000, softness: 1 },
  },
  {
    id: "backlit",
    group: "sceneLightGroupMood",
    label: "sceneLightBacklitLabel",
    hint: "sceneLightBacklitHint",
    prompt: "sceneLightBacklitPrompt",
    values: { azimuth: 180, elevation: 18, intensity: 8, temperature: 5800, softness: 0.2 },
  },
  {
    id: "single-hard",
    group: "sceneLightGroupMood",
    label: "sceneLightSingleHardLabel",
    hint: "sceneLightSingleHardHint",
    prompt: "sceneLightSingleHardPrompt",
    values: { azimuth: 95, elevation: 25, intensity: 5, temperature: 4800, softness: 0.05 },
  },
  {
    id: "night-neon",
    group: "sceneLightGroupMood",
    label: "sceneLightNightNeonLabel",
    hint: "sceneLightNightNeonHint",
    prompt: "sceneLightNightNeonPrompt",
    values: { azimuth: 130, elevation: 50, intensity: 2.2, temperature: 8500, softness: 0.4 },
  },
];

export const LIGHTING_PRESETS = PRESETS;
export const CUSTOM_PRESET = "custom";

export function presetById(id: string): LightingPreset | undefined {
  return PRESETS.find((preset) => preset.id === id);
}

/** 按声明顺序分组 —— 顺序是有意排的(默认档在最前),不要在这里重排。 */
export function presetGroups(): [MessageKey, LightingPreset[]][] {
  const groups: [MessageKey, LightingPreset[]][] = [];
  for (const preset of PRESETS) {
    const last = groups[groups.length - 1];
    if (last && last[0] === preset.group) last[1].push(preset);
    else groups.push([preset.group, [preset]]);
  }
  return groups;
}

/**
 * 交给模型的那段话。
 *
 * 选了预设就用它写好的;手动调过(custom)就按当时的**数**生成一句 —— 那时没有现成的说法,
 * 而"什么都不说"会让模型自己发挥,正是这一整套要避免的。
 */
export function lightingPrompt(lighting: SceneLighting, t: (key: MessageKey) => string): string {
  const preset = presetById(lighting.preset);
  if (preset) return t(preset.prompt);
  const warmth =
    lighting.temperature <= 3400 ? "sceneLightWarm" : lighting.temperature >= 6800 ? "sceneLightCool" : "sceneLightNeutral";
  const height =
    lighting.elevation >= 70 ? "sceneLightOverhead" : lighting.elevation <= 20 ? "sceneLightLowAngle" : "sceneLightMidHeight";
  const side =
    lighting.azimuth > 135 && lighting.azimuth < 225
      ? "sceneLightFromBehind"
      : lighting.azimuth > 45 && lighting.azimuth < 315
        ? "sceneLightFromSide"
        : "sceneLightFromFront";
  const edge =
    lighting.softness >= 0.6 ? "sceneLightSoftShadows" : lighting.softness <= 0.2 ? "sceneLightHardShadows" : "sceneLightNaturalShadows";
  return t("sceneLightCustomPrompt")
    .replace("{side}", t(side))
    .replace("{height}", t(height))
    .replace("{warmth}", t(warmth))
    .replace("{edge}", t(edge));
}


/**
 * 色温 → 线性 RGB。用的是 Tanner Helland 那条广为流传的近似,足够表达"暖/中性/冷"的区别。
 *
 * **不做成物理准确的黑体辐射**:这里的用途是让参考帧上的光看起来是那个色温,好让模型跟着走;
 * 精确到多少 K 对应哪个坐标点,对这个用途没有任何影响。
 */
export function kelvinRgb(kelvin: number): [number, number, number] {
  const t = Math.min(40000, Math.max(1000, kelvin)) / 100;
  const channel = (value: number) => Math.min(1, Math.max(0, value / 255));
  const red = t <= 66 ? 255 : 329.698727446 * (t - 60) ** -0.1332047592;
  const green =
    t <= 66 ? 99.4708025861 * Math.log(t) - 161.1195681661 : 288.1221695283 * (t - 60) ** -0.0755148492;
  const blue = t >= 66 ? 255 : t <= 19 ? 0 : 138.5177312231 * Math.log(t - 10) - 305.0447927307;
  return [channel(red), channel(green), channel(blue)];
}

/**
 * 主光的方向单位向量。方位角 0 是 +Z(相机默认所在的一侧),顺时针转向 +X;仰角 90 是正上方。
 *
 * 后端的白模渲染器有同一份(`scene_render/raster.sun_direction`):同一个场景,预览里影子朝
 * 左而参考图里朝右,给生成模型的光照提示就是错的。两份实现由 contracts/scene-3d-cases.json 钉住。
 * 放在这里而不是视口内部,是因为契约测试要够得着它 —— 藏在组件闭包里的公式验不了。
 */
export function sunDirection(azimuth: number, elevation: number): [number, number, number] {
  const a = (azimuth * Math.PI) / 180;
  const e = (elevation * Math.PI) / 180;
  return [Math.sin(a) * Math.cos(e), Math.sin(e), Math.cos(a) * Math.cos(e)];
}
