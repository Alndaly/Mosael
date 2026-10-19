/**
 * 把一段要念的文字切成句子 —— **只在「对话类」的组合层用**。
 *
 * 文件类(工作流「语音合成」节点、画板音配音、笔记「存成素材」)一次拿完整段:那是要落成素材的
 * 东西,半段音频没有意义。这里的切分只服务「边合成边播」的那几条对话路(免提、消息喇叭、笔记朗读)。
 *
 * 规则:
 * - 句末标点 `。！？；` 与 `. ! ? ;` 处切;
 * - **不切**在引号里(引号收在句末的,切在收引号之后)、省略号(`……` / `...`)、行内代码、代码块、
 *   URL、小数 / 版本号里;
 * - 换行也是一个自然停顿;段落之间的停顿比句间长(`PARAGRAPH_GAP_MS`);
 * - 空行、缩进不念。
 *
 * 它只管"从哪儿切",不管"怎么念" —— 取音频、排队、打断都在 `features/agent/speechPipeline`。
 */

export interface SpokenChunk {
  /** 要送去合成的一段文字。 */
  text: string;
  /** 这一段念完、下一段开始前留多长(段落之间留一点自然间隙)。 */
  gapAfterMs: number;
}

/** 段落之间留的自然间隙。一段话连着念下来会像机器在赶时间。 */
export const PARAGRAPH_GAP_MS = 280;

const TERMINALS = new Set(["。", "！", "？", "；", ".", "!", "?", ";", "．"]);
const QUOTE_PAIRS: Record<string, string> = { "“": "”", "‘": "’", "「": "」", "『": "』" };
const QUOTE_CLOSERS = new Set(["”", "’", "」", "』"]);
const CLOSING_BRACKETS = new Set(["）", ")", "】", "]"]);
/** `.` 属于缩写的一部分时不切(Mr. Smith / e.g. this)。 */
const ABBREVIATIONS = new Set([
  "mr", "mrs", "ms", "dr", "prof", "sr", "jr", "st", "vs", "etc", "e.g", "i.e", "no", "fig",
  "inc", "ltd", "co", "approx", "jan", "feb", "mar", "apr", "jun", "jul", "aug", "sep", "sept",
  "oct", "nov", "dec",
]);
const URL_START = /^(?:https?:\/\/|ftp:\/\/|www\.)/i;
const URL_CHAR = /[A-Za-z0-9\-._~:/?#[\]@!$&'()*+,;=%]/;

function isSpace(ch: string): boolean {
  return ch === " " || ch === "\t" || ch === "\u00a0";
}

function isLineBreak(ch: string): boolean {
  return ch === "\n" || ch === "\r";
}

function isAbbreviation(text: string, dot: number): boolean {
  const word = /([A-Za-z.]+)\.$/.exec(text.slice(Math.max(0, dot - 20), dot + 1));
  return word ? ABBREVIATIONS.has(word[1].toLowerCase()) : false;
}

/** 一个 `.`:是句号而不是省略号 / 小数 / 文件扩展名 / URL 里的点。 */
function dotEndsSentence(text: string, at: number): boolean {
  const next = text[at + 1] ?? "";
  if (!(next === "" || /\s/.test(next) || next === '"' || next === "'" || next === "”" || next === "’" || next === "」" || next === "』" || next === ")" || next === "]" || next === "）" || next === "】")) return false;
  return !isAbbreviation(text, at);
}

/** 这一段还有**字**可念吗:字母 / 数字 / 汉字才算字。`|---|---|`、`……`、纯 emoji 没有。 */
const HAS_WORDS = /[\p{L}\p{N}]/u;

/**
 * 只剩下符号的段落**不必送去合成**。
 *
 * 合成那头的出口会先把 markdown 洗一遍(`domain/voices/speakable`),洗完只剩符号就说「没有可念的
 * 文本」。对话这条路上,表格分隔行 `|---|---|`、单独一行省略号都是**切句切出来的段落** —— 把它们
 * 送去只会换回一次 422,用户听到/看到的却是「念失败」。真正该发生的是:这一段跳过,接着念下一句。
 *
 * 它只回答「有没有字」,不负责洗文本 —— 洗只有后端那**一处**(否则又是两份规则)。
 */
export function hasSpeakableContent(text: string): boolean {
  return HAS_WORDS.test(text);
}

export function splitSpeech(text: string): SpokenChunk[] {
  const chunks: SpokenChunk[] = [];
  let start = 0;
  let i = 0;
  let fence = false;
  let inlineCode = false;
  const quotes: string[] = [];

  const push = (end: number, gapAfterMs: number) => {
    const piece = text.slice(start, end).trim();
    //: 只剩符号的段落不念(见 hasSpeakableContent):它是切句切出来的,送去只会换回一次失败。
    if (piece && hasSpeakableContent(piece)) chunks.push({ text: piece, gapAfterMs });
  };

  while (i < text.length) {
    const ch = text[i];

    // 代码块 / 行内代码里的标点不是句子:原样留着,不在里面切。
    if (text.startsWith("```", i)) {
      fence = !fence;
      i += 3;
      continue;
    }
    if (fence) {
      i += 1;
      continue;
    }
    if (ch === "`") {
      inlineCode = !inlineCode;
      i += 1;
      continue;
    }
    if (inlineCode) {
      i += 1;
      continue;
    }

    // URL 里的点是地址的一部分。停在空白、引号、中文句末标点之前。
    if (URL_START.test(text.slice(i, i + 8))) {
      let j = i;
      while (j < text.length && URL_CHAR.test(text[j])) j += 1;
      // 网址末尾紧跟的句号 / 叹号是句子的,不是网址的。
      while (
        j > i &&
        (text[j - 1] === "." || text[j - 1] === "!" || text[j - 1] === "?" || text[j - 1] === ";") &&
        (j >= text.length || /\s/.test(text[j]))
      ) {
        j -= 1;
      }
      i = j;
      continue;
    }

    if (ch === '"') {
      if (quotes[quotes.length - 1] === '"') quotes.pop();
      else quotes.push('"');
      i += 1;
      continue;
    }
    if (QUOTE_PAIRS[ch]) {
      quotes.push(QUOTE_PAIRS[ch]);
      i += 1;
      continue;
    }
    if (QUOTE_CLOSERS.has(ch)) {
      if (quotes[quotes.length - 1] === ch) quotes.pop();
      i += 1;
      continue;
    }

    // 换行:一个自然停顿(段落之间那一个给得长一点)。引号里的换行不算。
    if (isLineBreak(ch) && quotes.length === 0) {
      let j = i;
      while (j < text.length && isLineBreak(text[j])) j += 1;
      push(i, PARAGRAPH_GAP_MS);
      start = j;
      i = j;
      continue;
    }

    if (TERMINALS.has(ch)) {
      // 省略号 `...` 是语气,不是句号。
      if (ch === ".") {
        let run = i;
        while (text[run] === ".") run += 1;
        if (run - i >= 2) {
          i = run;
          continue;
        }
        if (!dotEndsSentence(text, i)) {
          i += 1;
          continue;
        }
      }

      let end = i + 1;
      // `？！`「……?」这类连着的句末标点算同一处。
      while (end < text.length && TERMINALS.has(text[end]) && text[end] !== ".") end += 1;

      // 收引号、收括号跟着这一句走 —— 这样切点落在引号外,不是引号里。
      let cut = end;
      for (;;) {
        if (cut < text.length && quotes.length > 0 && quotes[quotes.length - 1] === text[cut]) {
          quotes.pop();
          cut += 1;
          continue;
        }
        if (cut < text.length && CLOSING_BRACKETS.has(text[cut])) {
          cut += 1;
          continue;
        }
        break;
      }

      // 还在引号里:这个句号属于引文内部,不切。
      if (quotes.length > 0) {
        i = end;
        continue;
      }

      let next = cut;
      let gapAfterMs = 0;
      while (next < text.length && (isSpace(text[next]) || isLineBreak(text[next]))) {
        if (isLineBreak(text[next])) gapAfterMs = PARAGRAPH_GAP_MS;
        next += 1;
      }
      push(cut, gapAfterMs);
      start = next;
      i = next;
      continue;
    }

    i += 1;
  }

  push(text.length, 0);
  return chunks;
}
