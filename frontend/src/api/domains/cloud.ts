import { api } from "@/api/transport";

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
