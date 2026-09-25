import type { BoardItem } from "@/api/client";
import type { MessageKey } from "@/app/messages";
import type { CanvasSearchEntry } from "@/components/app/CanvasNodeSearch";
import { kindText } from "@/features/boards/boardNodes";

/** 列表里一行放得下的长度。便签可以写很长,整段塞进一行只会被截成省略号。 */
const TITLE_CHARS = 60;

/**
 * 画板上哪些字该被「查找节点」搜到。
 *
 * 起了名的格子,列表里显示的就是**它的名字** —— 用户给它起名,正是为了在一排「图片」里认出它。
 * 没起名的大多也有能认的字:便签的"名字"就是它的正文,生成出来的图的"名字"是当初那句提示词。
 * 所以没名字时标题取**第一行正文**,没有就取提示词,都没有才退到类型(「图片」);名字、正文全文、
 * 提示词全文和类型的原始值(`image`,英文界面里按类型搜)都参与匹配,只是不全显示。
 */
export function boardSearchEntries(items: readonly BoardItem[], t: (key: MessageKey) => string): CanvasSearchEntry[] {
  return items.map((item) => {
    const kind = kindText(t, item.kind).label;
    const name = item.title?.trim() ?? "";
    const text = item.text?.trim() ?? "";
    const prompt = item.form?.prompt?.trim() ?? "";
    const firstLine = (name || text || prompt).split("\n")[0]!.trim();
    const title = firstLine ? (firstLine.length > TITLE_CHARS ? `${firstLine.slice(0, TITLE_CHARS)}…` : firstLine) : kind;
    return { id: item.id, title, subtitle: kind, text: [name, text, prompt, item.kind].filter(Boolean) };
  });
}
