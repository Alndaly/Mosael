import * as React from "react";

/**
 * ModalShell 里那张表单的 id(给了 `onSubmit` 才有):footer 里的 `ModalSubmit` 用它 `form=` 指过去。
 * 单独一个模块:context 的身份是这一次 `createContext` 返回的对象,和 UI 组件住在一起的话热更新会重造一个(见 app/contextIdentity.test.ts)。
 */
export const ModalFormContext = React.createContext<string | null>(null);

export function useModalFormId(): string | null {
  return React.useContext(ModalFormContext);
}
