import React from "react";

/**
 * 画布上此刻选中了两格以上:选中格子自己的出入口 `+` 收起来,只在悬停那一格时露出(和没选中的格子一样)。
 * 一次连好几格走选区框的统一出口(BoardSelectionOutlet),一组格子四周再挂满 `+` 只会和它挤在一起;
 * 单拉一根仍然可以 —— 指到那一格上,它的 `+` 就出来了。
 *
 * 由画布提供、格子的 Ports 读。住在这个不引 UI 的模块里:热更新重跑格子组件时 context 的身份不变(见 app/contextIdentity.test)。
 */
export const QuietPortsContext = React.createContext(false);
