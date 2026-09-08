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
import type { SceneLighting } from "@/api/domains/scenes";

export type LightingPreset = {
  id: string;
  group: string;
  label: string;
  /** 一句话说清它适合什么 —— 选择器里每一档下面那行。 */
  hint: string;
  /** 交给模型的那段话。**只描述光,不描述场景** —— 场景由参考帧和用户自己的提示词说。 */
  prompt: string;
  values: Omit<SceneLighting, "preset">;
};

const PRESETS: LightingPreset[] = [
  {
    id: "studio-soft",
    group: "产品与静物",
    label: "棚拍柔光",
    hint: "大面积柔光箱,影子淡而干净。默认档",
    prompt: "柔和的棚拍布光，大面积柔光箱从左前上方打下，阴影淡而边缘柔和，中性白平衡，没有杂乱的反光",
    values: { azimuth: 35, elevation: 55, intensity: 2.5, temperature: 5500, softness: 0.7 },
  },
  {
    id: "product-crisp",
    group: "产品与静物",
    label: "硬光高反差",
    hint: "边缘锐利的投影,金属和质感更抓眼",
    prompt: "硬光直射，投影边缘锐利、对比强烈，高光收得很紧，突出材质与轮廓的质感",
    values: { azimuth: 55, elevation: 40, intensity: 4, temperature: 5200, softness: 0.08 },
  },
  {
    id: "desk-window",
    group: "产品与静物",
    label: "桌面窗光",
    hint: "侧面自然光,像摆在窗边拍的",
    prompt: "单侧自然窗光从画面一侧斜射进来，柔和的方向性光线，暗部保留细节，像清晨摆在窗边拍摄",
    values: { azimuth: 80, elevation: 30, intensity: 2.8, temperature: 6000, softness: 0.55 },
  },
  {
    id: "portrait-soft",
    group: "人物",
    label: "柔和正面",
    hint: "接近顺光,面部干净、少阴影",
    prompt: "柔和的正面人像布光，面部均匀受光、阴影很浅，肤色自然通透",
    values: { azimuth: 15, elevation: 45, intensity: 2.4, temperature: 5200, softness: 0.8 },
  },
  {
    id: "portrait-rim",
    group: "人物",
    label: "侧逆轮廓",
    hint: "从身后侧方来,勾一圈亮边",
    prompt: "侧逆光勾出人物轮廓，发丝与肩线上有一圈明亮的边缘光，正面偏暗、层次分明",
    values: { azimuth: 205, elevation: 35, intensity: 5, temperature: 6200, softness: 0.25 },
  },
  {
    id: "portrait-warm",
    group: "人物",
    label: "暖调室内",
    hint: "室内灯的暖色,松弛、生活感",
    prompt: "室内暖光，色温偏暖近似白炽灯，光线柔和松弛，带有居家的生活感",
    values: { azimuth: 50, elevation: 40, intensity: 2.2, temperature: 3200, softness: 0.65 },
  },
  {
    id: "noon-sun",
    group: "空间与建筑",
    label: "正午天光",
    hint: "接近顶光,影子短而硬",
    prompt: "正午日光，接近顶光，投影短促而边缘清晰，天光明亮、色温偏冷",
    values: { azimuth: 20, elevation: 78, intensity: 4.5, temperature: 6000, softness: 0.12 },
  },
  {
    id: "golden-hour",
    group: "空间与建筑",
    label: "黄金时刻",
    hint: "低角度暖光,长投影",
    prompt: "黄昏黄金时刻的低角度阳光，暖金色调，投影拉得很长，空气中有淡淡的通透感",
    values: { azimuth: 250, elevation: 12, intensity: 3.6, temperature: 3000, softness: 0.3 },
  },
  {
    id: "overcast",
    group: "空间与建筑",
    label: "阴天均匀",
    hint: "几乎没有方向性,适合看形体",
    prompt: "阴天的均匀漫射光，几乎没有明显方向性，阴影极淡，颜色还原真实",
    values: { azimuth: 0, elevation: 80, intensity: 1.6, temperature: 7000, softness: 1 },
  },
  {
    id: "backlit",
    group: "氛围",
    label: "逆光剪影",
    hint: "光从正后方来,主体压成暗形",
    prompt: "强逆光，光源在主体正后方，主体接近剪影、只留轮廓，背景明亮并有光晕",
    values: { azimuth: 180, elevation: 18, intensity: 8, temperature: 5800, softness: 0.2 },
  },
  {
    id: "single-hard",
    group: "氛围",
    label: "单侧硬光",
    hint: "一侧亮一侧黑,戏剧感",
    prompt: "单一硬光源从侧面打来，明暗对比强烈，一半沉入阴影，带有戏剧性的紧张感",
    values: { azimuth: 95, elevation: 25, intensity: 5, temperature: 4800, softness: 0.05 },
  },
  {
    id: "night-neon",
    group: "氛围",
    label: "夜景霓虹",
    hint: "暗底 + 冷色主光,夜戏用",
    prompt: "夜晚场景，环境很暗，冷色调的人造光从侧上方打下，高光偏青蓝，暗部保留少量细节",
    values: { azimuth: 130, elevation: 50, intensity: 2.2, temperature: 8500, softness: 0.4 },
  },
];

export const LIGHTING_PRESETS = PRESETS;
export const CUSTOM_PRESET = "custom";

export function presetById(id: string): LightingPreset | undefined {
  return PRESETS.find((preset) => preset.id === id);
}

/** 按声明顺序分组 —— 顺序是有意排的(默认档在最前),不要在这里重排。 */
export function presetGroups(): [string, LightingPreset[]][] {
  const groups: [string, LightingPreset[]][] = [];
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
export function lightingPrompt(lighting: SceneLighting): string {
  const preset = presetById(lighting.preset);
  if (preset) return preset.prompt;
  const warmth =
    lighting.temperature <= 3400 ? "暖色调" : lighting.temperature >= 6800 ? "冷色调" : "中性白平衡";
  const height =
    lighting.elevation >= 70 ? "接近顶光" : lighting.elevation <= 20 ? "低角度" : "中等高度";
  const side =
    lighting.azimuth > 135 && lighting.azimuth < 225
      ? "从主体后方"
      : lighting.azimuth > 45 && lighting.azimuth < 315
        ? "从侧面"
        : "从正面";
  const edge =
    lighting.softness >= 0.6 ? "阴影柔和" : lighting.softness <= 0.2 ? "投影边缘锐利" : "阴影过渡自然";
  return `主光${side}${height}打来，${warmth}，${edge}`;
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
