import React from "react";

/**
 * 确认卡上批的人能拨的开关(后端 `ConfirmationOut.choices`,如改技能那几张卡的「建好就启用」)。
 *
 * 开关画在卡里那个工具自己的预览上(只有它知道摆在哪),批准按钮却是外面给的(对话里、全局中心各给各的)——
 * 两边要读写同一份值,所以由卡(ConfirmationCard)持有、经这个上下文递给两边:按钮点下去时把它带进批准请求。
 * 单独一个模块:预览组件和卡互相引用的话,谁先被加载谁就读到一个还没初始化的对方。
 */
export interface CardChoices {
  values: Record<string, boolean>;
  set: (name: string, value: boolean) => void;
}

const NO_CHOICES: CardChoices = { values: {}, set: () => undefined };

export const CardChoicesContext = React.createContext<CardChoices>(NO_CHOICES);

export function useCardChoices(): CardChoices {
  return React.useContext(CardChoicesContext);
}
