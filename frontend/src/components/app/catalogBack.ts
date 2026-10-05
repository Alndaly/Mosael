import React from "react";

/**
 * 目录弹窗(CatalogDialog)详情页固定头最前面的那颗返回键。由弹窗做好(它管焦点:进详情时给它,退回网格时还给那张卡),
 * 放进上下文 —— 详情页的头(CatalogDetail,或插件市场自己的 PluginHero)经 CatalogBackSlot 取出来摆在最前面,
 * `renderDetail` 的写法不用变。不在目录弹窗的详情里时是 null。
 *
 * 单独一个只依赖 React 的模块:context 的身份是那一次 createContext,和 UI 组件住在一起的话,热更新整个重跑那个模块,
 * 外层的 Provider 和里面读的就不是同一个了(见 app/contextIdentity.test)。
 */
export const CatalogBack = React.createContext<React.ReactNode>(null);

export function useCatalogBack(): React.ReactNode {
  return React.useContext(CatalogBack);
}
