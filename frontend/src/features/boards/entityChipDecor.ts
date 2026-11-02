import { createContext, type ReactNode } from "react";

/**
 * 正文里资产 chip 的「装饰」:由用这个编辑器的那一格决定,和 AI Studio 引用小条(`entityMentionChips`)同一套 ——
 * `onOpen` 点小条看预览,`accessory` 挂在名字后面的那颗小控件(姿势引用的「按普通参考图发送」)。
 *
 * 单独住一个只依赖 React 的模块:`PromptEditor` 引着 TipTap 和 UI 组件,`createContext` 留在那里会让
 * 热更新重跑整个编辑器模块、换出一个新的 context。context 的身份必须和 UI 的依赖链分开。
 *
 * 走 context 而不是节点属性:它们是这一格此刻的状态(模型收不收姿势、勾没勾),不是文档内容,
 * 不该存进 TipTap JSON。节点视图经 portal 渲染在 EditorContent 底下,读得到外面这层 context。
 */
export interface EntityChipDecor {
  onOpen?: (entityId: string) => void;
  /** 只挂在这个资产在正文里**第一次**出现的那条上:同一个姿势 `@` 两次,开关也只有一档。 */
  accessory?: (entityId: string) => ReactNode;
}

export const NO_DECOR: EntityChipDecor = {};

export const EntityChipDecorContext = createContext<EntityChipDecor>(NO_DECOR);
