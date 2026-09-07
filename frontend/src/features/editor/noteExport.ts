import type { NoteSource } from "@/api/domains/notes";
import type { SaveToNoteVariant } from "@/features/notes/SaveToNote";

/** 导出到笔记的一行:一句逐字稿,或一条字幕。时间是**时间线时间**,与用户在面板上看到的一致。 */
export interface NoteExportLine {
  text: string;
  /** 双语字幕的第二行;没有就留空。 */
  secondary?: string;
  start: number;
  end: number;
  /** 这句话出自哪个素材;拿不到就只导正文,不伪造出处。 */
  assetId?: string;
}

/** 正文形状。两种都保留,因为它们服务两件不同的事:
 *  ・`plain` —— 当稿子用。句子直接连成段落,时间戳只留在文档底部的来源区;
 *  ・`cited` —— 当记录用。每句一个引用块 + 时间,回看时能一句一句对回视频。 */
export type NoteExportFormat = "plain" | "cited";

export interface NoteExportDraft {
  markdown: string;
  sources: NoteSource[];
}

function seconds(value: number): string {
  return value.toFixed(1);
}

/** 同一段话里相邻的句子并成一个自然段;停顿超过这个秒数就另起一段。
 *  纯粹是可读性:一整页不分段的文字没人愿意读,而说话人的停顿正是天然的段落线。 */
const PARAGRAPH_BREAK_SECONDS = 1.5;

function lineText(line: NoteExportLine): string {
  const primary = line.text.trim();
  const secondary = line.secondary?.trim();
  return secondary && secondary !== primary ? `${primary}\n${secondary}` : primary;
}

function plainMarkdown(lines: NoteExportLine[]): string {
  const paragraphs: string[] = [];
  let current: string[] = [];
  lines.forEach((line, index) => {
    const text = lineText(line);
    if (!text) return;
    const previous = lines[index - 1];
    // 双语行自带换行,并进段落会把两种语言揉成一团 —— 让它独占一段。
    if (current.length && (line.secondary || previous?.secondary
      || line.start - previous.end >= PARAGRAPH_BREAK_SECONDS)) {
      paragraphs.push(current.join(""));
      current = [];
    }
    current.push(text);
  });
  if (current.length) paragraphs.push(current.join(""));
  return paragraphs.filter(Boolean).join("\n\n");
}

function citedMarkdown(lines: NoteExportLine[], label: string): string {
  return lines
    .map((line) => {
      const text = lineText(line);
      if (!text) return "";
      return `> ${text.replace(/\n/g, "\n> ")}\n\n${label} · ${seconds(line.start)}–${seconds(line.end)}s`;
    })
    .filter(Boolean)
    .join("\n\n");
}

/**
 * 把一组句子做成一份可写进笔记的草稿。
 *
 * **两种形状共用同一份来源(sources)** —— 出处是事实,不随排版变;变的只是正文怎么读。
 * 这也是它必须收在一处的原因:此前逐字稿那个按钮把正文和 sources 各拼一遍,字幕页则
 * 干脆没有入口,于是"同一份内容导出来不一样"是迟早的事。
 */
export function buildNoteExport(
  lines: NoteExportLine[],
  format: NoteExportFormat,
  label: string,
): NoteExportDraft {
  const usable = lines.filter((line) => lineText(line));
  return {
    markdown: format === "cited" ? citedMarkdown(usable, label) : plainMarkdown(usable),
    sources: usable.flatMap((line) =>
      line.assetId
        ? [{ kind: "asset" as const, id: line.assetId, label, quote: lineText(line),
             start: line.start, end: line.end }]
        : []),
  };
}

/**
 * 两种形状做成「保存到笔记」对话框认的可选项。
 *
 * 收在这里而不是各面板各拼一次:逐字稿与字幕导出的是不同内容,但**可选哪几种形状、各叫
 * 什么名字**是同一件事 —— 让它有两处定义,就是让两个面板迟早给出不一样的选项。
 */
export function noteExportVariants(
  lines: NoteExportLine[],
  label: string,
  names: { shapePlain: string; shapeCited: string },
): SaveToNoteVariant[] {
  return [
    { id: "plain", label: names.shapePlain, ...buildNoteExport(lines, "plain", label) },
    { id: "cited", label: names.shapeCited, ...buildNoteExport(lines, "cited", label) },
  ];
}
