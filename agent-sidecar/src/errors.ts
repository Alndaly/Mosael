/**
 * 一个错误的整句,**连同它的 cause 链**:`ModelsError: OAuth refresh failed for kimi-coding: Kimi Code token refresh
 * unauthorized (status 400): The provided authorization grant is invalid`。
 *
 * pi 刷新失败时抛的是包了一层的 ModelsError,外面那层只说「刷新失败了」,对方说了什么(invalid_grant、400)在 cause 里。
 * 后端靠那一句判「是对方不认这份凭据了(要重新授权),还是只是网络不通」(见 backend providers.auth.refresh_was_rejected),
 * 只交外层那一句就判不出来。
 */
export function describeError(error: unknown): string {
  const parts: string[] = [];
  let current: unknown = error;
  for (let depth = 0; current !== undefined && current !== null && depth < 5; depth += 1) {
    const text = current instanceof Error ? (depth === 0 ? String(current) : current.message) : String(current);
    if (text && !parts.some((part) => part.includes(text))) parts.push(text);
    current = current instanceof Error ? (current as { cause?: unknown }).cause : undefined;
  }
  return parts.join(": ");
}
