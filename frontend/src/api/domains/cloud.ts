import { ApiError, apiAllowingUnauthorized } from "@/api/transport";
import { errorText } from "@/api/errorMessage";

/**
 * 桌面端的 MosaelCloud 账号(云端 `/api/cloud/v1/*`,经**本机后端**转发)。
 *
 * 为什么走本机后端而不是直接打 Cloud:Cloud 只接受官网同源、不开 CORS;而且桌面端在云端的凭据
 * (登录时换来的设备令牌,ADR 0088)由本机后端存着(加密列 `cloud_login`),**渲染层从头到尾看不到它**。
 * 登录成功只回 `{email}`。
 *
 * 这些接口的 401 说的是「MosaelCloud 那边没登录」,**不是**这台机器上的账号退出了 —— 所以统一
 * 走 `apiAllowingUnauthorized`,不触发本地的 401 处理。
 */

export type CloudSession = { email: string };

/** 一次云端失败的形状:后端给的人话 + 机器码 + 是不是"这个部署没接 Cloud"。 */
export type CloudFailure = {
  status: number;
  code: string;
  message: string;
  notConfigured: boolean;
};

/** 把一次失败拆成界面要的三样。`message` 就是后端那句人话(409/401/429 各自一句)。 */
export function describeCloudFailure(error: unknown): CloudFailure {
  if (error instanceof ApiError) {
    let code = "";
    try {
      const parsed = JSON.parse(error.body) as { detail?: { code?: unknown } };
      if (typeof parsed.detail?.code === "string") code = parsed.detail.code;
    } catch {
      //: 不是 JSON(网关的 HTML 错误页)—— 保留状态码和那句原文就够了。
    }
    return {
      status: error.status,
      code,
      message: errorText(error),
      notConfigured: error.status === 503 && code === "cloud_not_configured",
    };
  }
  return { status: 0, code: "", message: errorText(error), notConfigured: false };
}

/** 现在登的是谁。没登录是 401 —— 调用方据此显示登录表单。 */
export function getCloudSession(): Promise<CloudSession> {
  return apiAllowingUnauthorized<CloudSession>("/api/cloud/v1/me");
}

/** 现在登的是谁;**没登录是 `null`,不是一次失败**(README 那句「401 只是还没登」)。 */
export async function loadCloudSession(): Promise<CloudSession | null> {
  try {
    return await getCloudSession();
  } catch (error) {
    if (error instanceof ApiError && error.status === 401) return null;
    throw error;
  }
}

/** 邮箱 + 密码登录。成功只回邮箱;设备令牌由本机后端落盘。 */
export function loginWithPassword(email: string, password: string): Promise<CloudSession> {
  return apiAllowingUnauthorized<CloudSession>("/api/cloud/v1/login", {
    method: "POST",
    body: JSON.stringify({ email, password }),
  });
}

/** 验证码登录第一步:让云端把 6 位码发到这个邮箱。未注册邮箱也回同一句。 */
export function requestCloudLoginCode(email: string): Promise<{ sent: boolean }> {
  return apiAllowingUnauthorized<{ sent: boolean }>("/api/cloud/v1/login/code", {
    method: "POST",
    body: JSON.stringify({ email }),
  });
}

/** 验证码登录第二步:码换会话。 */
export function verifyCloudLoginCode(email: string, code: string): Promise<CloudSession> {
  return apiAllowingUnauthorized<CloudSession>("/api/cloud/v1/login/code/verify", {
    method: "POST",
    body: JSON.stringify({ email, code }),
  });
}

/** 退出桌面端的云端登录:本机后端撤掉云端那一份会话,再删本地那一行。 */
export function logoutCloud(): Promise<void> {
  return apiAllowingUnauthorized<void>("/api/cloud/v1/logout", { method: "POST" });
}
