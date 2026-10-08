/**
 * 播客「照稿念」的稿子(ADR 0055 §6):一段一轮,每段是谁念、念什么。火山播客照 `nlp_texts` 念,上限 60 段、每段 280 字 ——
 * 这两个数是接口的,前后端一起守(后端 voices.start_podcast / 适配器同样拦)。
 */

export const MAX_SCRIPT_TURNS = 60;
export const MAX_TURN_CHARS = 280;

/** 一段:`speaker` 是发音人 A(0)还是 B(1)。 */
export type ScriptTurn = { speaker: 0 | 1; text: string };

/** 下一段默认换另一位念(对谈就是这么来回的)。 */
export function otherSpeaker(speaker: 0 | 1): 0 | 1 {
  return speaker === 0 ? 1 : 0;
}

const PREFIX_SEPARATOR = /^\s*([^::\n]{1,24})\s*[::]\s*/;

/**
 * 一大段粘进来的字拆成几段:一行一段(空行跳过)。行首写了谁说的(`A:` / `B:`,全角冒号也认;或者发音人的名字,「大壹先生:」)就照它,
 * 认不出的行接着上一段的下一位念。`names` 是 A、B 两位的名字(下拉里那个);`start` 是第一段在没写前缀时归谁。
 */
export function parseScript(text: string, names: readonly [string, string], start: 0 | 1 = 0): ScriptTurn[] {
  const turns: ScriptTurn[] = [];
  let next: 0 | 1 = start;
  for (const raw of text.split(/\r?\n/)) {
    const line = raw.trim();
    if (!line) continue;
    const found = PREFIX_SEPARATOR.exec(line);
    const who = found ? speakerOf(found[1], names) : null;
    const speaker = who ?? next;
    const body = who === null ? line : line.slice(found![0].length).trim();
    if (!body) continue;
    turns.push({ speaker, text: body });
    next = otherSpeaker(speaker);
  }
  return turns;
}

function speakerOf(prefix: string, names: readonly [string, string]): 0 | 1 | null {
  const key = prefix.trim().toLowerCase();
  if (key === "a") return 0;
  if (key === "b") return 1;
  const short = (name: string) => name.replace(/[((].*$/, "").trim().toLowerCase();
  if (names[0] && (key === names[0].trim().toLowerCase() || key === short(names[0]))) return 0;
  if (names[1] && (key === names[1].trim().toLowerCase() || key === short(names[1]))) return 1;
  return null;
}

/** 稿子交得出去吗:有一段以上、不超过 60 段、每段不超过 280 字。 */
export function scriptProblems(turns: readonly ScriptTurn[]): { empty: boolean; tooMany: boolean; tooLong: number[] } {
  const filled = turns.filter((turn) => turn.text.trim());
  return {
    empty: filled.length === 0,
    tooMany: filled.length > MAX_SCRIPT_TURNS,
    tooLong: turns.flatMap((turn, index) => (turn.text.trim().length > MAX_TURN_CHARS ? [index] : [])),
  };
}

/**
 * 一段做好的播客的对谈稿 → 稿子(「改稿再念」):`dialogue` 里每段记着念它的音色,`speakers` 是这次的 A、B。
 * 认不出是谁的那段(不在这两位里)接着上一段的下一位。
 */
export function scriptFromDialogue(
  dialogue: readonly { speaker: string; text: string }[],
  speakers: readonly string[],
): ScriptTurn[] {
  let next: 0 | 1 = 0;
  return dialogue
    .filter((line) => line.text.trim())
    .map((line) => {
      const index = speakers.indexOf(line.speaker);
      const speaker: 0 | 1 = index === 0 || index === 1 ? index : next;
      next = otherSpeaker(speaker);
      return { speaker, text: line.text.trim() };
    });
}
