/**
 * 金额(micros)→ 一句人能读的话。**全项目只有这一份。**
 *
 * **不同币种的钱不相加。**后端每一处汇总都给 `costs: CostAmount[]` —— 每个币种一笔,主要币种
 * (计过价次数最多的那种)在前(见 backend domain/usage.CostAmount)。此前界面拿到的是一个把
 * 人民币和美元加在一起、再随便贴上其中一种单位的数:¥12 + $4.5 显示成「16.5 USD」。
 * 这里也不做汇率换算 —— 汇率随日子变,换算出来的数没人能对账。
 *
 * 小额必须留够精度:`toFixed(2)` 会把一次几厘钱的调用压成 `0.00` —— 管理页曾因此出现
 * 「花得最多的那个人」条形拉满、旁边写着 ¥0.00 的自相矛盾(真机截图)。
 * 符号按界面语言的习惯来(Intl 的 currency 格式):中文界面 `¥12.30`、`US$4.50`,英文界面
 * `CN¥12.30`、`$4.50` —— 两种钱并排时各自带着自己的单位,不会认错。
 */

export type CostAmount = { currency: string; micros: number };

function digitsFor(amount: number): Intl.NumberFormatOptions {
  // 不到一分钱:保留两位有效数字(0.0015),否则一次对话的钱全是 0.00。
  if (amount > 0 && amount < 0.01) return { maximumSignificantDigits: 2 };
  if (amount < 1) return { minimumFractionDigits: 2, maximumFractionDigits: 4 };
  if (amount < 100) return { minimumFractionDigits: 2, maximumFractionDigits: 2 };
  return { minimumFractionDigits: 0, maximumFractionDigits: 0 };
}

/** 一个币种下的一笔钱。 */
export function formatMoney(micros: number, currency: string, locale?: string): string {
  const amount = Math.max(0, micros) / 1_000_000;
  const digits = digitsFor(amount);
  try {
    return new Intl.NumberFormat(locale, { style: "currency", currency, ...digits }).format(amount);
  } catch {
    // 规则里手填了一个 Intl 不认的币种代码(不是三个字母)—— 照样显示,单位原样跟在后面。
    return `${new Intl.NumberFormat(locale, digits).format(amount)} ${currency}`;
  }
}

/** 一组各币种的钱:`¥12.30 + US$4.50`。空列表返回空串,由调用方决定"没有钱"怎么说。 */
export function formatCosts(costs: readonly CostAmount[] | null | undefined, locale?: string): string {
  return (costs ?? []).map((cost) => formatMoney(cost.micros, cost.currency, locale)).join(" + ");
}

/**
 * 前端手里只有逐条事件时(对话页脚),按币种各自求和 —— 和后端 `costs_by_currency` 同一个
 * 规矩:只在同一币种内相加,次数多的币种在前,次数相同按币种代码。
 */
export function sumByCurrency(amounts: Iterable<CostAmount>): CostAmount[] {
  const totals = new Map<string, { micros: number; count: number }>();
  for (const { currency, micros } of amounts) {
    const entry = totals.get(currency) ?? { micros: 0, count: 0 };
    entry.micros += micros;
    entry.count += 1;
    totals.set(currency, entry);
  }
  return [...totals.entries()]
    .sort(([a, x], [b, y]) => y.count - x.count || a.localeCompare(b))
    .map(([currency, { micros }]) => ({ currency, micros }));
}

/** 某个币种下的那一笔;这个币种没有钱时是 0。图表按币种取值用。 */
export function microsIn(costs: readonly CostAmount[] | null | undefined, currency: string): number {
  return (costs ?? []).find((cost) => cost.currency === currency)?.micros ?? 0;
}
