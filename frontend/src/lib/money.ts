/**
 * 金额(micros)→ 一句人能读的话。**全项目只有这一份。**
 *
 * 小额必须留够小数位:`toFixed(2)` 会把一次几厘钱的调用压成 `0.00` —— 管理页曾因此出现
 * 「花得最多的那个人」条形拉满、旁边写着 ¥0.00 的自相矛盾(真机截图)。
 * 币种也由调用方给,不写死符号:按 USD 计价的部署不该看到人民币符号。
 */
export function formatMicros(value: number, currency: string): string {
  if (value <= 0) return `0 ${currency}`;
  const amount = value / 1_000_000;
  if (amount < 1) return `${amount.toFixed(4)} ${currency}`;
  if (amount < 100) return `${amount.toFixed(2)} ${currency}`;
  return `${Math.round(amount).toLocaleString()} ${currency}`;
}
