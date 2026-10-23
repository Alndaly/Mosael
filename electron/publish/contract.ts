/**
 * **平台页面契约**:一个平台"发布这件事"长什么样,写成数据。
 *
 * 收之前,这些事实散在三处:「按形状进哪一页」在适配器顶上的表里、「提交按钮叫什么」在 selectors
 * 里、「发完算什么成功」在适配器自己的 `waitResult` 里、「挡路的浮层怎么关」又是另一套。
 * 加一种形状 / 一个平台就得同时改三处,漏一处就出现"填好了、点不了、或者发成功了却判失败"。
 *
 * 契约只写**事实**,不写流程 —— 流程在执行器(`publishWorker` 的步骤管道)。
 * 平台特有的动作(小红书的逗号成段、抖音的 zone 编辑器、B 站封面)仍留在适配器里。
 */
import type { ContentKind } from "./types";
import type { OverlayRule } from "./overlays";
import type { SuccessSignals } from "./verify";

/** 一种形状怎么落到那一页上。 */
export interface KindEntry {
  /** 直连地址(平台的页面参数):比"进去再点 tab"确定得多,能躲开点不中 / SPA 没渲染。 */
  url?: string;
  /** 没有直连时,按顺序要点的 tab 文案。 */
  steps?: readonly string[];
  /** 落到之后当前选中的 tab 文案(最可靠的"这是目标页"判据)。 */
  activeTab?: string;
  /** 这一档接受的文件扩展名(给"是不是这一档的输入框"做判据)。 */
  acceptExtensions?: readonly string[];
  /** 这一档的拖放区提示文案。 */
  hint?: string;
}

export interface PlatformContract {
  /** 入口:按形状。没写的形状 = 适配器还没接(见 `supports`)。 */
  entry: Partial<Record<ContentKind, KindEntry>>;
  /** 上传入口:按形状挑文件输入框(按 `accept` 区分,**不猜**)。 */
  fileInput: Partial<Record<ContentKind, string>>;
  /** 提交那颗按钮的文案(发布 / 发布笔记 / 立即发布…)。 */
  submitText: string;
  /** 发布成功的信号。**按可靠性排**:地址 > 平台接口 > 文案(见 verify.ts 的原语)。 */
  done: SuccessSignals;
  /** 会挡路的浮层(见 overlays.ts):认它、关它。 */
  overlays: readonly OverlayRule[];
}
