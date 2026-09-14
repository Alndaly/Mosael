/**
 * 把一次失败的接口调用变成**一句给人看的话**。
 *
 * 后端的错误几乎都写成了可读的中文(「只有视频或音频素材可以转写」「这个素材没有音轨」),
 * 而此前抛出的是 `422 Unprocessable Content: {"detail":"…"}` —— 那句话原样出现在界面上,
 * 前面顶着状态码、状态短语、JSON 括号和 "detail" 这个键名。后三样对使用者没有任何意义。
 *
 * 取不出 detail 时才退回状态码:那时确实没有更好的话可说,而一句空白比一个数字更糟。
 */
export function humanError(status: number, statusText: string, body: string): string {
  try {
    const parsed = JSON.parse(body) as { detail?: unknown };
    const detail = parsed.detail;
    if (typeof detail === "string" && detail.trim()) return detail;
    if (Array.isArray(detail)) {
      // pydantic 的校验错误:[{loc, msg, ...}]
      const parts = detail
        .map((item) => (item && typeof item === "object" ? String((item as { msg?: unknown }).msg ?? "") : String(item)))
        .filter(Boolean);
      if (parts.length) return parts.join(";");
    }
  } catch {
    // 不是 JSON(网关的 HTML 错误页之类)——退回状态码。
  }
  return `${status} ${statusText}`.trim();
}

/**
 * 错误对象里**该给人看的那一句**。
 *
 * `String(err)` 走的是 `Error.prototype.toString()`,它会把 `name` 贴回句首 —— 于是
 * 后端那句干净的「笔记不存在」在界面上变成「ApiError: 笔记不存在」。类名是给写代码的人
 * 看的,不是给正在写笔记的人看的。
 */
export function errorText(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}
