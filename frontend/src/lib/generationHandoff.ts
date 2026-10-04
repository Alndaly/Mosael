import { writePersistentTab } from "@/lib/usePersistentTab";

/**
 * 别的页面把「用这个模型 / 这几项参数去生成」交给 AI 工作台 —— 模型库的「用它生成」:选中能用这个文件的那张工作流、
 * 选模型文件的那一格填上它、LoRA 的触发词接在提示词末尾。
 *
 * 交接是「点一下马上跳过去」的事:记在这一次页面会话的内存里(刷新就没了,不留在存储里等下次莫名其妙生效),
 * 把工作台切到管这一种的那一页,跳过去;那一页清单到了之后取走一次(`takeGenerationHandoff`)。
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
  // AI 工作台记着上次停在哪一页:图像 / 视频在「生成」页,音频在「音频」页的「音乐与音效」(见 AiStudio / AudioWorkspace)
  if (handoff.kind === "audio") {
    writePersistentTab("ai-studio", "audio");
    writePersistentTab("ai-studio-audio", "music");
  } else {
    writePersistentTab("ai-studio", "generate");
  }
  window.location.hash = "#/ai";
}

/** 管这几种的那一页取走交过来的那一份;不是它管的、或者没有,就是 null。取走一次就没了。 */
export function takeGenerationHandoff(kinds: readonly string[]): GenerationHandoff | null {
  if (!pending || !kinds.includes(pending.kind)) return null;
  const handoff = pending;
  pending = null;
  return handoff;
}
