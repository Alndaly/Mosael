/**
 * 把「用户说的一句话」对到「哪个选项」上。
 *
 * **拿不准就说拿不准,不猜。** 这是这整块里最容易出错、也最难发现的一处:识别本来就会错字,
 * 而选项之间往往只差一两个词("先改模板" / "先改主题")。猜错的代价不是报错 —— 是它顺着
 * 一条你没选的路一直做下去,而你以为自己选的是另一条。
 *
 * 所以判据是保守的:**必须唯一命中**。命中两个、一个都不命中,都退回去再问一次(或者让人
 * 在屏幕上点)。多问一句的成本,远低于沿着错路走十步。
 *
 * 三种说法都认,因为人本来就这三种说:
 *
 *   · 说序号 —— 「第一个」「第二个」「一」
 *   · 说标签 —— 「告白场景」
 *   · 说标签的一部分 —— 「告白」
 */

export type ChoiceMatch =
  | { kind: "picked"; index: number }
  /** 命中不止一个 —— 让人再说一次,别替他挑。 */
  | { kind: "ambiguous"; indexes: number[] }
  /** 一个都没命中。 */
  | { kind: "none" };

/** 序号的说法。写全是因为它们真的都会出现,而漏一种就是一次"没听懂"。 */
const ORDINALS: Record<string, number> = {
  第一个: 0, 第一: 0, 一: 0, 首个: 0, first: 0, one: 0, "1": 0,
  第二个: 1, 第二: 1, 二: 1, 两: 1, second: 1, two: 1, "2": 1,
  第三个: 2, 第三: 2, 三: 2, third: 2, three: 2, "3": 2,
  第四个: 3, 第四: 3, 四: 3, fourth: 3, four: 3, "4": 3,
  第五个: 4, 第五: 4, 五: 4, fifth: 4, five: 4, "5": 4,
  第六个: 5, 第六: 5, 六: 5, sixth: 5, six: 5, "6": 5,
};

/** 归一化:识别结果常带标点和空格,而「告白场景。」和「告白场景」是同一句。 */
function normalize(text: string): string {
  return text
    .toLocaleLowerCase()
    .replace(/[\s\p{P}\p{S}]+/gu, "")
    .trim();
}

export function matchSpokenChoice(said: string, options: string[]): ChoiceMatch {
  const heard = normalize(said);
  if (!heard || options.length === 0) return { kind: "none" };

  // 序号优先:「第二个」在标签里几乎不会出现,而它是最明确的一种表达。
  for (const [word, index] of Object.entries(ORDINALS)) {
    if (index < options.length && heard === normalize(word)) return { kind: "picked", index };
  }

  const labels = options.map(normalize);
  // 完全一致优先于包含 —— 否则一个标签是另一个的前缀时("导出" / "导出并发布"),
  // 说全了反而会变成"命中两个"。
  const exact = labels.flatMap((label, index) => (label && label === heard ? [index] : []));
  if (exact.length === 1) return { kind: "picked", index: exact[0] };
  if (exact.length > 1) return { kind: "ambiguous", indexes: exact };

  const contained = labels.flatMap((label, index) =>
    label && (heard.includes(label) || label.includes(heard)) ? [index] : [],
  );
  if (contained.length === 1) return { kind: "picked", index: contained[0] };
  if (contained.length > 1) return { kind: "ambiguous", indexes: contained };
  return { kind: "none" };
}
