import type { CommunityShareKind } from "@/api/domains/shares";
import { ApiError, ApiOfflineError, isNotFound } from "@/api/transport";
import type { MessageKey } from "@/app/messages";

/**
 * 社区分享导入在**渲染层**这一小段:把深链投递用的 `share:` 标记拆出来,以及把一次失败归成
 * 三种人分得清的类别(分享不在 / 连不上 / 内容不对),各自配一句下一步。
 *
 * 真正导入走现有的 `POST /api/workflows/import`;这里不解析、也不相信 payload 的内容。
 */

/**
 * 深链解析器(见 electron/system/deepLink)把分享 id 藏在 `share:` 前缀后面,借工作流社区
 * 「选中模板」那条信箱投递进来 —— 页面挂载得晚也能收到(见 lib/deepLink 的 useOpenRequest)。
 */
export const SHARE_IMPORT_PREFIX = "share:";

/** 分享 id 的字符集:和 electron/system/deepLink 的 SHARE_PATTERN 同一份判据。渲染层再验一次。 */
const SHARE_PATTERN = /^[A-Za-z0-9_-]{1,64}$/;

/** 从模板通道里认出分享 id;不是分享(真模板 id、坏值、注入)就返回 null。 */
export function shareFromTemplate(template: string): string | null {
  if (typeof template !== "string" || !template.startsWith(SHARE_IMPORT_PREFIX)) return null;
  const share = template.slice(SHARE_IMPORT_PREFIX.length);
  return SHARE_PATTERN.test(share) ? share : null;
}

/**
 * 只做「能不能交给后端」这一层形状判断:导入接口要的是一个 JSON 对象。
 *
 * **格式、版本、节点结构一律不在前端判断** —— 那是后端 `mosael_formats.workflow_file` 的事,
 * 前端猜一遍只会多出一套会和后端分叉的规则。
 */
export function importablePayload(payload: unknown): Record<string, unknown> | null {
  if (!payload || typeof payload !== "object" || Array.isArray(payload)) return null;
  return payload as Record<string, unknown>;
}

/** 一次失败属于哪一类 —— 决定界面上那句下一步是什么。 */
export type ShareFailureKind = "notFound" | "offline" | "invalid" | "other";

export function classifyShareFailure(error: unknown): ShareFailureKind {
  if (error instanceof ApiOfflineError || (error as { offline?: unknown } | null)?.offline === true) return "offline";
  if (isNotFound(error)) return "notFound";
  if (error instanceof ApiError && (error.status === 400 || error.status === 413 || error.status === 422)) return "invalid";
  return "other";
}

/** 后端 / 传输层给的那句话(可能为空)。只用在「详情」里,不替换我们自己那句人话。 */
export function failureMessage(error: unknown): string {
  if (error instanceof Error) return error.message.trim();
  return typeof error === "string" ? error.trim() : "";
}

/**
 * 一类失败 → 一张 `FailureCard` 要的三样:一句话、原文(有才给)、怎么走下一步。
 * **每一种都给得出一条下一步** —— 只说「失败了」等于把人留在原地。
 */
export function shareFailureCopy(
  t: (key: MessageKey) => string,
  kind: ShareFailureKind,
  detail: string,
): { summary: string; detail: string | null; fix: { steps: { text: string }[] } } {
  if (kind === "notFound") {
    return { summary: t("shareImportNotFound"), detail: null, fix: { steps: [{ text: t("shareImportNotFoundFix") }] } };
  }
  if (kind === "offline") {
    return { summary: t("shareImportOffline"), detail: null, fix: { steps: [{ text: t("shareImportOfflineFix") }] } };
  }
  if (kind === "invalid") {
    return {
      summary: t("shareImportInvalid"),
      //: 后端原话(「不是 Mosael 工作流文件」这类)收进「详情」:它比我们的概括更具体,但不该压过那句概括。
      detail: detail || null,
      fix: { steps: [{ text: t("shareImportInvalidFix") }] },
    };
  }
  return { summary: detail || t("shareImportFailed"), detail: null, fix: { steps: [{ text: t("shareImportOtherFix") }] } };
}

/** 类型那一格显示什么。 */
export function shareKindLabel(t: (key: MessageKey) => string, kind: CommunityShareKind): string {
  return kind === "board" ? t("shareImportKindBoard") : t("shareImportKindWorkflow");
}

/**
 * **画板分享没有自动导入接口。** 后端 `routes/boards.py` 只有建 / 改 / 复制 / 跑,没有 import;
 * 不在这条链路上现造一个(那等于自己写一套画板文件格式)。所以画板只说明「先去官网下载文件手动导入」。
 */
export function shareCanImport(kind: CommunityShareKind | undefined): boolean {
  return kind === "workflow";
}
