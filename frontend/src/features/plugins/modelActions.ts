import React from "react";

import type { ModelFile } from "@/api/client";
import type { GenerationTarget } from "@/features/plugins/modelLibraryView";

/**
 * 模型库里对一个模型能做的事(右键菜单、详情页用,见 ModelMenu)。context 单放一个只依赖 React 和类型的模块:
 * 和界面组件住在一起的话,改一个按钮热更新时 context 会被重新造一个(见 app/contextIdentity.test.ts)。
 *
 * 这几样本事由模型库弹窗给(见 ModelLibraryDialog 的 useModelActions);卡片、列表行、详情页从上下文里拿。
 */
export type ModelActions = {
  open: (model: ModelFile) => void;
  /** 打开详情并跳到「在用的工作流」那一节。 */
  openUsed: (model: ModelFile) => void;
  /** 能用它生成的工作流(见 modelLibraryView.generationTargets);生成选项还在读时是空的、`targetsLoading()` 为真。 */
  targets: (model: ModelFile) => GenerationTarget[];
  targetsLoading: () => boolean;
  generate: (model: ModelFile, target: GenerationTarget) => void;
  /** 大图:应用共用的灯箱,能左右翻当前筛出来的那一批。没有能看的图时是 null(说为什么)。 */
  showLarge: (model: ModelFile) => void;
  largeUnavailable: (model: ModelFile) => string | null;
  /** 手动标 NSFW(`null` 去掉标记)。 */
  markNsfw: (model: ModelFile, nsfw: boolean | null) => void;
  /** 打开原站上那一页(在浏览器里)。 */
  openSource: (model: ModelFile) => void;
  /** 在 Civitai 上找(一个后台任务);找不了、正在找时说为什么。 */
  lookUp: (model: ModelFile) => void;
  lookupUnavailable: (model: ModelFile) => string | null;
  /** 存为预览图(先确认);写不回时说缺什么。 */
  savePreview: (model: ModelFile) => void;
  saveUnavailable: (model: ModelFile) => string | null;
};

export const ModelActionsContext = React.createContext<ModelActions | null>(null);
