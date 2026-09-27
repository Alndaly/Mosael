import type { ErrorBody } from "@/lib/community/types";

/**
 * 社区服务回的错。
 *
 * 服务的错误体统一是 `{"error": {"code", "message"}}`,message 已按 Accept-Language 译好 ——
 * 页面直接显示 message,按 code 做分支(比如 `authorization_pending`)。读不出错误体时(反代的
 * 502 页、断网)code 用 `http_<状态码>` / `network`,message 留空,由页面给一句通用的话。
 */
export class CommunityError extends Error {
  readonly status: number;
  readonly code: string;

  constructor(status: number, code: string, message: string) {
    super(message || code);
    this.name = "CommunityError";
    this.status = status;
    this.code = code;
  }
}

function isErrorBody(value: unknown): value is ErrorBody {
  if (!value || typeof value !== "object") return false;
  const error = (value as { error?: unknown }).error;
  return Boolean(error && typeof error === "object" && typeof (error as { code?: unknown }).code === "string");
}

export async function errorFromResponse(response: Response): Promise<CommunityError> {
  let body: unknown = null;
  try {
    body = await response.json();
  } catch {
    body = null;
  }
  if (isErrorBody(body)) return new CommunityError(response.status, body.error.code, body.error.message ?? "");
  return new CommunityError(response.status, `http_${response.status}`, "");
}

export function networkError(): CommunityError {
  return new CommunityError(0, "network", "");
}
