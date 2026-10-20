import { ApiError, ApiOfflineError, api } from "@/api/transport";

/**
 * 本地后端保存的 MosaelCloud 绑定(见 backend/app/api/routes/cloud.py)。
 *
 * 路径只写在这里 —— 界面代码里不现拼 `/api/…`(design/apiSeam.test.ts 盯着)。
 */

export type CloudBindingStatus = {
  bound: boolean;
  email?: string | null;
  device_id?: string | null;
  created_at?: string | null;
};

export type CloudBindingIssued = {
  status: "pending_authorization";
  /** 短期轮询码。不是账号凭据;真正的云端 token 不经过渲染层。 */
  device_code: string;
  user_code: string;
  verification_uri: string;
  verification_uri_complete: string;
  expires_in: number;
  interval: number;
};

export type CloudBindingCompleted = {
  status: "pending" | "approved";
  email?: string | null;
  device_id?: string | null;
};

/**
 * 一次绑定操作失败后**给人看的那一摊**:后端原样转述的云端错误码、一句人话,以及两种要换说法的情形。
 *
 * 「过期 / 已用」的码要原样显示(`device_code_expired` / `device_code_used`):这句话比任何翻译都准,
 * 用户拿它去搜、去报问题都对得上。连不上则不该露出 `cloud_unreachable` 这种机器词,换成「连不上 MosaelCloud」。
 */
export type CloudBindingFailure = {
  code: string | null;
  message: string;
  unreachable: boolean;
  notConfigured: boolean;
};

/** 把一次失败拆成「错误码 + 一句话 + 是不是连不上」。 */
export function describeCloudBindingFailure(error: unknown): CloudBindingFailure {
  const message = error instanceof Error ? error.message : String(error);
  let code: string | null = null;
  if (error instanceof ApiError) {
    try {
      const detail = (JSON.parse(error.body) as { detail?: { code?: unknown } }).detail;
      if (detail && typeof detail.code === "string" && detail.code.trim()) code = detail.code;
    } catch {
      // 不是 JSON(网关的 HTML 错误页之类):没有码可转述,只剩那句话。
    }
  }
  const offline = error instanceof ApiOfflineError || (error as { offline?: unknown } | null)?.offline === true;
  return {
    code,
    message,
    unreachable: offline || code === "cloud_unreachable",
    notConfigured: code === "cloud_not_configured",
  };
}

export function getCloudBinding(): Promise<CloudBindingStatus> {
  return api<CloudBindingStatus>("/api/cloud/binding");
}

export function startCloudBinding(deviceName = "Mosael desktop"): Promise<CloudBindingIssued> {
  return api<CloudBindingIssued>("/api/cloud/binding/start", {
    method: "POST",
    body: JSON.stringify({ device_name: deviceName }),
  });
}

export function completeCloudBinding(deviceCode: string): Promise<CloudBindingCompleted> {
  return api<CloudBindingCompleted>("/api/cloud/binding/complete", {
    method: "POST",
    body: JSON.stringify({ device_code: deviceCode }),
  });
}

export function unbindCloudBinding(): Promise<{ removed: boolean }> {
  return api<{ removed: boolean }>("/api/cloud/binding", { method: "DELETE" });
}
