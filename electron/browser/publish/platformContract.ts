/**
 * **平台页面契约**:一个平台"发布这件事"长什么样,写成数据。
 *
 * 收之前,这些事实散在三处:「按形状进哪一页」在适配器顶上的表里、「提交按钮叫什么」在 selectors
 * 里、「发完算什么成功」在适配器自己的 `waitResult` 里、「挡路的浮层怎么关」又是另一套。
 * 加一种形状 / 一个平台就得同时改三处,漏一处就出现"填好了、点不了、或者发成功了却判失败"。
 *
 * 契约只写**事实**,不写流程 —— 流程在执行器(`runPublishTask`)。
 * 标题 / 正文 / 标签等**填表字段**也在这里按内容形状声明(见 `fields`),适配器只做平台特有动作。
 */
import type { ContentKind } from "./publishTypes";
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

export interface PlatformFields {
  /** 标题输入框;与正文同栏的平台两键指向同一 selector。 */
  title: string;
  /** 正文 / 简介输入框。 */
  body: string;
  /** 标签输入位置;没有独立标签栏时与正文同栏。 */
  tags: string;
  /** 平台额外描述的输入位置(通常是简介或摘要)。 */
  description?: string;
  /** 平台额外短标题的输入位置。 */
  shortTitle?: string;
}

export interface PlatformContract {
  /** 各内容形状的字段 selector;适配器只从这里取标题、正文和标签位置。 */
  fields: Partial<Record<ContentKind, PlatformFields>>;
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
