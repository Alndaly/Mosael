/**
 * 「顶上那条搜索框里现在这串字」:库里的卡片 / 列表行拿它标出名字里命中的那几个字(见 ModelLibrary 的 ModelFileName)。
 *
 * 为什么不是一层层当 prop 传下去:模型库的卡片是**记忆化**的(见 ModelGrid)—— 搜索框里每敲一个字,已经画着的那几十张卡
 * 连同预览图都重画一遍是不必要的,真的变的只有名字那一小块。读这个 context 的小组件自己重画,卡片本身照旧跳过
 * (ModelLibrary.virtual.dom.test.tsx 钉着这条)。
 *
 * **单独一个模块、只依赖 React**(app/contextIdentity.test.ts):context 的身份就是那一次 `createContext` 返回的对象,
 * 它所在的模块被热更新重跑一次就换出一个新的 —— 外层的 Provider 还是旧的,之后挂上的消费者读到的却是空的。
 */
import * as React from "react";

/** 搜索框里当前的字(原样,没 trim;空串 = 没在搜)。 */
export const LibrarySearchContext = React.createContext("");
