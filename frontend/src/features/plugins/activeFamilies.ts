import React from "react";

/**
 * 模型库按底模筛时勾着的那几种:文本编码器的「常配」把它们排前面、写重一点(卡片、列表、详情都读这一份,见 ModelEncoder)。
 * context 单放一个只依赖 React 的模块:和界面组件住在一起的话,改一个按钮热更新时 context 会被重新造一个
 * (见 app/contextIdentity.test.ts)。
 */
export const ActiveFamiliesContext = React.createContext<readonly string[]>([]);
