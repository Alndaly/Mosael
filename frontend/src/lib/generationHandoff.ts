import { gotoCreate, isCreateFilter } from "@/lib/aiStudioLink";

/**
 * 别的页面把「用这个模型 / 这几项参数去生成」交给 AI 工作台 —— 模型库的「用它生成」:选中能用这个文件的那张工作流、
 * 选模型文件的那一格填上它、LoRA 的触发词接在提示词末尾。
 *
 * 交接是「点一下马上跳过去」的事:记在这一次页面会话的内存里(刷新就没了,不留在存储里等下次莫名其妙生效),
 * 跳到创作分区、筛选换成这一种;清单到了之后取走一次(`takeGenerationHandoff`)。
 */
export type GenerationHandoff = {
  providerProfileId: string;
  kind: string;
  model: string;
  /** 模型声明的参数(键 → 值):ComfyUI 工作流里选大模型 / LoRA 的那一格。 */
  declared: Record<string, string>;
  /** 接在提示词末尾的词(作者写明的 LoRA 触发词),提示词里已有的不重复加。 */
  promptWords: string[];
};

let pending: GenerationHandoff | null = null;

export function handOffToGeneration(handoff: GenerationHandoff): void {
  pending = handoff;
  //: 创作分区,筛选换成这一种(ADR 0055 §9)—— 交过来的模型在那一种的清单里。
  gotoCreate(isCreateFilter(handoff.kind) ? handoff.kind : undefined);
}

/** 创作页取走交过来的那一份;没有就是 null。取走一次就没了。 */
export function takeGenerationHandoff(): GenerationHandoff | null {
  const handoff = pending;
  pending = null;
  return handoff;
}
