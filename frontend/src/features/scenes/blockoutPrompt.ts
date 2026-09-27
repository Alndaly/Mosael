/**
 * 从 3D 场景「生成素材」时写进生成格的那段提示词。
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
import type { MessageKey } from "@/app/messages";
import type { SceneObject } from "@/api/domains/scenes";
import { hiddenObjectIds } from "./sceneGraph";

/** 清单要看的那几个字段。带上 id/parent_id 是为了算"上级藏没藏"(见下)。 */
type InventoryObject = Pick<SceneObject, "id" | "parent_id" | "name" | "kind" | "hidden">;

/** 不出现在画面里的物体:相机、灯、分组本身。 */
const OFFSCREEN = new Set(["camera", "light", "group"]);
/** 新建物体时的默认名(「Box 3」「Object」)对模型没有信息量,不列。 */
const DEFAULT_NAME = /^(object|box|sphere|cylinder|plane|room|stairs|group|model|light|figure|table|camera)(\s*\d+)?$/i;
const MAX_LISTED = 12;

/** 画面里有什么:「列柱 ×12、神像、石阶」。同名的合并计数,按出现次数多的在前。
 *
 *  **藏起来的不列,连同藏起来的组里的东西** —— 参考帧和视频里画不出它们,清单再说"画面里有",
 *  模型就会凭空补一个出来。此前只看物体自己那一位,藏一个组时组里的东西照样上了清单。 */
export function sceneInventory(
  objects: readonly InventoryObject[],
  t: (key: MessageKey) => string,
): string {
  const counts = new Map<string, number>();
  const hidden = hiddenObjectIds(objects);
  for (const object of objects) {
    const name = object.name.trim();
    if (hidden.has(object.id) || OFFSCREEN.has(object.kind) || !name || DEFAULT_NAME.test(name)) continue;
    counts.set(name, (counts.get(name) ?? 0) + 1);
  }
  return [...counts.entries()]
    .sort((a, b) => b[1] - a[1])
    .slice(0, MAX_LISTED)
    .map(([name, count]) => (count > 1 ? `${name} ×${count}` : name))
    .join(t("sceneListSeparator"));
}

/**
 * 从 3D 场景「生成素材」时,生成格提示词框里先写好的那几句:画面里有什么、打光是什么。按界面语言写 —— 人要看、要改。
 *
 * 「参考是白模、只取构图和运镜、成品要写实」那几句**不在这里**:参考是服务端生成时现渲的(ADR 0029),说明也由它
 * 随参考一起附上(后端 sceneRef_*),连进来的场景不管从哪条路来都有,不靠这一段被留在提示词框里。
 */
export function sceneBriefPrompt({
  objects,
  lighting,
  t,
}: {
  objects: readonly InventoryObject[];
  /** 打光预设那段话(lightingPrompt 的结果),不带句号。 */
  lighting: string;
  t: (key: MessageKey) => string;
}): string {
  const inventory = sceneInventory(objects, t);
  const lines = [inventory ? t("sceneBlockoutInventory").replace("{items}", inventory) : "", t("sceneBlockoutLighting").replace("{lighting}", lighting)];
  return lines.filter(Boolean).join(t("sceneSentenceGap"));
}
