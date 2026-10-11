/**
 * 「表上的一项该用哪一格画」—— 一处判据,面板和预览都从它拿,**顺序就是表上的顺序**。
 *
 * 为什么要有这个文件:精简表单有两处把它画出来 —— 生成面板的「引擎参数」按表上的顺序、用表上的名字摆
 * (见 GenerateWorkspace 的 appFormPanel),表单编辑器右侧的预览此前却按自己分好的类摆(提示词 → 反向提示词 →
 * 素材槽按固定的角色顺序 → 尺寸 → 张数 → 种子 → 参数)。两处各排一套的后果,作者一眼就能撞上:在中间把「参考图」
 * 拖到「放大倍数」下面,预览里什么都看不出变化,而用的人看到的偏偏是面板那一份 —— 预览那句「看到的就是这样」
 * 当场落空。每认一种新键、每加一类格子,两边还得各改一遍,迟早又对不上。
 *
 * 所以这里只做**归类**:一项是提示词、反向提示词、种子、尺寸、张数、某个素材角色,还是描述符声明的参数。
 * 控件仍由各自那一侧提供 —— 面板那份状态是右栏正在编辑的配置,预览那份是本地试填、不存的,把 JSX 抽成公共组件
 * 只会把两套状态也搅在一起(见 PreviewPanel)。
 */
import type { GenerationOption } from "@/api/client";
import { sourceRoleOfKey } from "@/lib/generationCapabilities";
import { SOURCE_ROLES, type SourceRole } from "@/lib/sourceFrames";

export type AppFieldKind = "prompt" | "negative_prompt" | "seed" | "size" | "num_images" | "source" | "parameter";

export interface AppField {
  /** 表单上那一项的 key(表里怎么写就怎么算) */
  key: string;
  /** 这一格的标签(表单上作者起的名,空串表示用默认文案) */
  label: string;
  kind: AppFieldKind;
  /** kind === "source":哪个角色 */
  role?: SourceRole;
  /** kind === "parameter":在描述符 `parameter_schema` / `declaredParameters` 里的键 */
  parameterKey?: string;
}

/** 宿主自己的那几格:表上写这个键就是对到宿主的控件上(和后端 catalog 的宿主键同名)。 */
const HOST_KINDS: Record<string, AppFieldKind> = {
  prompt: "prompt",
  negative_prompt: "negative_prompt",
  seed: "seed",
  size: "size",
  num_images: "num_images",
};

function isSourceRole(key: string): key is SourceRole {
  return (SOURCE_ROLES as readonly string[]).includes(key);
}

/**
 * 表上每一项该用哪一格画,**顺序就是表上的顺序**。
 *
 * 判据和 GenerateWorkspace.appFormPanel 原来的 `field(item)` 逐条一致:
 * 五个宿主键 → 同名 kind;key 本身就是角色(插件把读素材的槽位直接写成了角色)→ `source`;
 * 否则按 `source_keys` 算出的角色(表上那一格是 `<节点>.<输入名>`)→ `source`,key 保留表上的写法;
 * 再认不出就是描述符声明的参数(`parameterKey` 就是表上的 key)——**参数键在描述符里有没有,这里不判**:
 * 认不出就不画是调用方的事(面板 `declaredField` 那边查 `parameter_schema`,预览那边查 `declaredParameters`)。
 *
 * 还有一条摆法上的规则也在这里:视频模型上首帧、尾帧是一个控件,表里两项都在时**尾帧那一项跳过**
 * (和面板原来的判据一样,先出现的首帧算数)。
 */
export function appFormFields(
  model: GenerationOption | null,
  items: readonly { key: string; label?: string }[],
): AppField[] {
  const fields: AppField[] = [];
  for (const item of items) {
    const label = item.label ?? "";
    const host = HOST_KINDS[item.key];
    if (host) {
      fields.push({ key: item.key, label, kind: host });
      continue;
    }
    //: 表单上挑的这一格其实是读素材的槽位(`49.image` 这种):画成传图 / 传视频的那一格,不是文件名下拉。
    const role = isSourceRole(item.key) ? item.key : sourceRoleOfKey(model, item.key);
    if (role && isSourceRole(role)) {
      //: 首帧和尾帧是一对、一个控件:表上两项都在时只摆一次。
      if (role === "last_frame" && model?.kind === "video" && fields.some((one) => one.role === "first_frame")) continue;
      fields.push({ key: item.key, label, kind: "source", role });
      continue;
    }
    fields.push({ key: item.key, label, kind: "parameter", parameterKey: item.key });
  }
  return fields;
}
