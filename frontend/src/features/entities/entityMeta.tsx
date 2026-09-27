import React from "react";
import { useQuery } from "@tanstack/react-query";
import { MapPin, Package, UserRound, type LucideIcon } from "lucide-react";

import { toast } from "sonner";

import {
  entityKeys,
  entityReceipt,
  getEntityCatalog,
  getJob,
  type EntityAttachReceipt,
  type EntityCatalog,
  type EntityKind,
} from "@/api/client";
import type { MessageKey } from "@/app/messages";
import { useI18n } from "@/app/preferences";

/**
 * 资产的图标和名字。**名字从后端的词表来**(`GET /api/entities/catalog`,按界面语言翻好):种类、参考图的角度、
 * 授权声明的选项和说明都只在后端存一份 —— 这里不另抄一张中英对照表。图标是界面自己的事。
 */
export const ENTITY_KIND_ICONS: Record<EntityKind, LucideIcon> = {
  character: UserRound,
  location: MapPin,
  prop: Package,
};

export function entityKindIcon(kind: string): LucideIcon {
  return ENTITY_KIND_ICONS[kind as EntityKind] ?? Package;
}

/** 词表只取一次:它随界面语言变,语言一换 App 会整页重取。`enabled`:还用不上时(弹窗没开)先不取。 */
export function useEntityCatalog(enabled = true) {
  return useQuery({ queryKey: entityKeys.catalog(), queryFn: getEntityCatalog, staleTime: Infinity, enabled });
}

export type CatalogLabels = {
  kind: (kind: string) => string;
  role: (role: string) => string;
  roles: { value: string; label: string }[];
  consent: EntityCatalog["consent_kinds"];
  /** 生成时挑参考图的先后(角度的名字):三视图 > 正面 > 全身,其余排在后面。 */
  priority: string[];
};

/** 词表还没到的时候用原值兜底 —— 一格空白比一个英文标识符更让人以为坏了。 */
export function catalogLabels(catalog: EntityCatalog | undefined): CatalogLabels {
  const kinds = new Map((catalog?.kinds ?? []).map((one) => [one.kind, one.label]));
  const roles = new Map((catalog?.roles ?? []).map((one) => [one.role, one.label]));
  return {
    kind: (kind) => kinds.get(kind) ?? kind,
    role: (role) => roles.get(role) ?? role,
    roles: (catalog?.roles ?? []).map((one) => ({ value: one.role, label: one.label })),
    consent: catalog?.consent_kinds ?? [],
    priority: (catalog?.attach_priority ?? []).map((role) => roles.get(role) ?? role),
  };
}

export function useCatalogLabels(enabled = true): CatalogLabels {
  const catalog = useEntityCatalog(enabled);
  return React.useMemo(() => catalogLabels(catalog.data), [catalog.data]);
}

/** 变体显示成「母体 · 变体」—— 「张三 · 冬装」和「张三」是同一个人。 */
export function entityDisplayName(entity: { name: string; parent_name?: string | null }): string {
  return entity.parent_name ? `${entity.parent_name} · ${entity.name}` : entity.name;
}

const NOTE_KEYS: Record<string, MessageKey> = {
  limit: "entityNote_limit",
  no_reference_role: "entityNote_no_reference_role",
  unknown_limits: "entityNote_unknown_limits",
  exclusive: "entityNote_exclusive",
  subject_too_few: "entityNote_subject_too_few",
  prompt_skipped: "entityNote_prompt_skipped",
};

/**
 * 一次生成里 `@` 到的资产挂了几张参考图、没挂上的为什么 —— 每个资产一行。全挂上了、也没别的话要说的资产不写。
 * AI 工作台的生成记录和画板提交之后的提示读的是同一份。
 */
export function receiptLines(receipt: EntityAttachReceipt[], t: (key: MessageKey) => string): string[] {
  return receipt
    .filter((row) => row.dropped.length > 0 || row.notes.length > 0)
    .map((row) => {
      const head = t("entityReceiptLine")
        .replace("{name}", row.name)
        .replace("{attached}", String(row.attached.length))
        .replace("{dropped}", String(row.dropped.length));
      const why = row.notes.map((note) => (NOTE_KEYS[note] ? t(NOTE_KEYS[note]) : note)).join(";");
      return why ? `${head} —— ${why}` : head;
    });
}

/** 生成记录上那一小段「挂了哪几张」。没有要说的就什么都不画。 */
export function EntityReceiptNote({ receipt }: { receipt: EntityAttachReceipt[] }) {
  const t = useI18n();
  const lines = receiptLines(receipt, t);
  if (lines.length === 0) return null;
  return (
    <div role="note" data-entity-receipt="" className="grid gap-0.5 rounded-md bg-secondary px-2.5 py-1.5 text-ui-xs text-muted-foreground">
      {lines.map((line) => (
        <span key={line}>{line}</span>
      ))}
    </div>
  );
}

/**
 * 画板上一格生成提交之后:`@` 到的资产(或连进来的资产格)有参考图没挂上,弹一句说明。回执在任务的请求里
 * (`payload.request.entities`),和 AI 工作台生成记录上那一段读的是同一份。取不到就不说 —— 这是补充说明,不是主流程。
 */
export async function announceEntityReceipt(jobId: string, t: (key: MessageKey) => string): Promise<void> {
  try {
    const job = await getJob(jobId);
    const request = (job.payload as Record<string, unknown> | undefined)?.request as Record<string, unknown> | undefined;
    const lines = receiptLines(entityReceipt(request), t);
    if (lines.length > 0) toast.info(t("entityReceiptTitle"), { description: lines.join("\n") });
  } catch {
    // 任务查不到(已被清掉)时没什么可说的 —— 生成本身照常进行。
  }
}
