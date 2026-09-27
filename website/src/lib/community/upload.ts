/**
 * 直传一个文件到社区服务的存储(ADR 0026 §5「先要上传地址 → 逐个文件 PUT → 提交」)。头像走这条路:
 * 传好之后 `PATCH /me {avatar_sha256}`。
 *
 * 文件按内容哈希去重:服务已经有这份(`skipped`)就不再传。上传地址是服务给的 —— 本地存储时是服务
 * 自己的 `/api/community/v1/uploads/…`(带签名),S3 时是预签名 URL;两种都不带我们的访问令牌。
 */
import { CommunityError, errorFromResponse, networkError } from "@/lib/community/errors";
import type { UploadsResponse } from "@/lib/community/types";

export async function sha256Hex(data: ArrayBuffer): Promise<string> {
  const digest = await crypto.subtle.digest("SHA-256", data);
  return [...new Uint8Array(digest)].map((byte) => byte.toString(16).padStart(2, "0")).join("");
}

type FetchJson = <T>(path: string, options?: { method?: string; json?: unknown }) => Promise<T>;

export async function uploadBlob(fetchJson: FetchJson, file: File): Promise<string> {
  const bytes = await file.arrayBuffer();
  const sha256 = await sha256Hex(bytes);
  const plan = await fetchJson<UploadsResponse>("/shares/uploads", {
    method: "POST",
    json: { files: [{ sha256, size: file.size, content_type: file.type || "application/octet-stream" }] },
  });
  for (const upload of plan.uploads.filter((one) => one.sha256 === sha256)) {
    let response: Response;
    try {
      response = await fetch(upload.url, { method: upload.method || "PUT", headers: upload.headers, body: bytes });
    } catch {
      throw networkError();
    }
    if (!response.ok) throw await errorFromResponse(response);
  }
  if (!plan.uploads.some((one) => one.sha256 === sha256) && !plan.skipped.includes(sha256)) {
    throw new CommunityError(500, "upload_missing", "");
  }
  return sha256;
}
