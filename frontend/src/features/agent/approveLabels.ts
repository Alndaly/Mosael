/**
 * 有的确认卡上「批准」有更贴切的说法:改 ComfyUI 画布那张(ADR 0042 拍板 3)摆的是一份改动清单,点的是「应用」—— 点了才改到
 * 画布上。按钮做的事不变(批准这一张);对话里的内联卡和右上角的全局中心都用这一份。
 */
import type { MessageKey } from "@/app/messages";

const APPROVE_LABELS: Partial<Record<string, MessageKey>> = {
  comfy_canvas_edit: "confirmApplyChanges",
};

export function approveLabel<K extends MessageKey>(tool: string, fallback: K): MessageKey {
  return APPROVE_LABELS[tool] ?? fallback;
}
