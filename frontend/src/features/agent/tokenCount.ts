/** 上下文用量、追踪面板里 token 数的紧凑写法:1234 → 1.2k,12345 → 12k。逐条消息的精确数不用它。 */
export function formatCompactTokens(value: number): string {
  if (value >= 1000) return `${(value / 1000).toFixed(value >= 10_000 ? 0 : 1)}k`;
  return String(value);
}
