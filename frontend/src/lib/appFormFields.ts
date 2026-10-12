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
 *
 * 归类之外只有一件事:表上首帧、尾帧两格都在时给它俩盖同一枚配对标记(见 AppFieldPair)——它在面板里是一个控件,
 * 在预览里是两格。**两格都留着**,谁也不少:归类不该替调用方决定少画一格(预览没有那个成对的控件,少画一格就是骗人)。
 */
import type { GenerationOption } from "@/api/client";
import { sourceRoleOfKey } from "@/lib/generationCapabilities";
import { SOURCE_ROLES, type SourceRole } from "@/lib/sourceFrames";

export type AppFieldKind = "prompt" | "negative_prompt" | "seed" | "size" | "num_images" | "source" | "parameter";

/**
 * 成对的两格由**同一个控件**画出来 —— 现在只有视频的首帧与尾帧:左边首帧、右边尾帧,中间一个对调箭头
 * (见 ai-studio/FrameSlotField.KeyframePairField)。表上两格都在时两格都盖这枚标记。
 */
export type AppFieldPair = "keyframes";

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
  /**
   * kind === "source":这一格和表上另一格是**一个控件里的两格**(见 AppFieldPair)。两格都留在表上,
   * 由「画成一个控件」的那一侧按它只画一次(生成面板);没这个控件的调用方(预览)照旧一格一格画。
   */
  pair?: AppFieldPair;
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
 * 表上每一项该用哪一格画,**顺序就是表上的顺序**,而且**一项都不少**。
 *
 * 判据和 GenerateWorkspace.appFormPanel 原来的 `field(item)` 逐条一致:
 * 五个宿主键 → 同名 kind;key 本身就是角色(插件把读素材的槽位直接写成了角色)→ `source`;
 * 否则按 `source_keys` 算出的角色(表上那一格是 `<节点>.<输入名>`)→ `source`,key 保留表上的写法;
 * 再认不出就是描述符声明的参数(`parameterKey` 就是表上的 key)——**参数键在描述符里有没有,这里不判**:
 * 认不出就不画是调用方的事(面板 `declaredField` 那边查 `parameter_schema`,预览那边查 `declaredParameters`)。
 *
 * 视频模型上首帧、尾帧在生成面板里是**一个控件里的两格**(见 FrameSlotField.KeyframePairField)。此前这里为了那一件事
 * 把尾帧那一项**丢掉**,可预览没有那个成对的控件、它一格一格画 —— 于是作者表上明明有「首帧」「尾帧」两格(维护者截图:
 * 视频工作流 `video_minimax_h3_i2v` 的「首尾帧生成视频」),预览里只剩首帧那一格,说的「看到的就是这样」当场落空。
 * 归类不该替调用方决定少画一格:两格都留着,只在两格都在时给它们盖同一枚 `pair`(见 AppFieldPair),
 * 由有那个控件的调用方按它只画一次(生成面板),预览照表画两格 —— 用的人看到几格,预览里就是几格。
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
      fields.push({ key: item.key, label, kind: "source", role });
      continue;
    }
    fields.push({ key: item.key, label, kind: "parameter", parameterKey: item.key });
  }
  //: 表上首帧、尾帧两格都在 → 它俩在生成面板里是同一个控件里的两格(见 AppFieldPair)。顺序不动,位置也不动。
  if (model?.kind === "video") {
    const first = fields.find((one) => one.role === "first_frame");
    const last = fields.find((one) => one.role === "last_frame");
    if (first && last) {
      first.pair = "keyframes";
      last.pair = "keyframes";
    }
  }
  return fields;
}
