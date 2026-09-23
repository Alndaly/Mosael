/**
 * 从 3D 场景「一键生成」时交给生成模型的那段提示词。
 *
 * ## 为什么要专门写
 *
 * 真机:白模运镜视频交给 Seedance,出来的视频和白模几乎一模一样 —— 灰色的柱子、灰色的地面。
 * 此前的提示词只有一句「参考 3D 场景的构图、空间布局和运镜,生成最终视频」:它说了**从参考里
 * 拿什么**,却没说**参考里什么不能要**,也没说**成片该是什么**。模型手上唯一具体的画面就是那段
 * 灰模,于是照着它画。
 *
 * 所以这段话要讲清三件事:
 *
 * 1. 参考是**白模预演**:灰白、无材质只是占位;只取运镜、机位、构图和物体位置。
 * 2. 画面里**有什么**:场景名 + 物体清单(白模里那些形状各是什么)—— 模型不知道一根灰色圆柱
 *    该长成石柱还是树干。
 * 3. 打光(打光预设那段话,见 lighting.ts)。
 *
 * 此前视频那条路上还挂着一句「另一张灰模参考图只用于读取光影与体积」—— 而视频路径根本没有
 * 第二张参考图,那句话指着一个不存在的输入。
 */
import type { SceneObject } from "@/api/domains/scenes";

/** 不出现在画面里的物体:相机、灯、分组本身。 */
const OFFSCREEN = new Set(["camera", "light", "group"]);
/** 新建物体时的默认名(「Box 3」「Object」)对模型没有信息量,不列。 */
const DEFAULT_NAME = /^(object|box|sphere|cylinder|plane|room|stairs|group|model|light|figure|table|camera)(\s*\d+)?$/i;
const MAX_LISTED = 12;

/** 画面里有什么:「列柱 ×12、神像、石阶」。同名的合并计数,按出现次数多的在前。 */
export function sceneInventory(objects: readonly Pick<SceneObject, "name" | "kind" | "hidden">[]): string {
  const counts = new Map<string, number>();
  for (const object of objects) {
    const name = object.name.trim();
    if (object.hidden || OFFSCREEN.has(object.kind) || !name || DEFAULT_NAME.test(name)) continue;
    counts.set(name, (counts.get(name) ?? 0) + 1);
  }
  return [...counts.entries()]
    .sort((a, b) => b[1] - a[1])
    .slice(0, MAX_LISTED)
    .map(([name, count]) => (count > 1 ? `${name} ×${count}` : name))
    .join("、");
}

export function blockoutPrompt({
  kind,
  sceneName,
  objects,
  lighting,
  clay,
}: {
  kind: "image" | "video";
  sceneName: string;
  objects: readonly Pick<SceneObject, "name" | "kind" | "hidden">[];
  /** 打光预设那段话(lightingPrompt 的结果),不带句号。 */
  lighting: string;
  /** 出图时是否另附了一张灰模渲染(只用来读光影与体积)。视频路径没有这张。 */
  clay: boolean;
}): string {
  const inventory = sceneInventory(objects);
  const lines =
    kind === "video"
      ? [
          `参考视频是 3D 场景「${sceneName}」的白模预演：只沿用它的运镜、机位节奏、构图和各物体的空间位置。`,
          "白模里灰白、没有材质的外观只是占位 —— 成片要是完整写实的画面，每样东西都换成真实的材质、纹理与细节，不要出现灰模、线框或未上材质的表面。",
        ]
      : [
          `参考图是 3D 场景「${sceneName}」的白模渲染：只沿用它的构图、空间布局与摄像机视角。`,
          "白模的纯色、无材质外观只是占位 —— 生成一张完整写实的精细图片，每样东西都换成真实的材质、纹理与细节。",
          clay ? "另一张灰模参考图只用于读取光影与体积，不要照搬它的灰色材质。" : "",
        ];
  if (inventory) lines.push(`画面里有：${inventory}（按参考里的位置与大小摆放）。`);
  lines.push(`打光：${lighting}。`);
  return lines.filter(Boolean).join("");
}
