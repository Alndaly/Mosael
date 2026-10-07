import React from "react";
import { Check, CircleAlert, Loader2, ShieldAlert, TriangleAlert, X } from "lucide-react";

import type { Confirmation } from "@/api/client";
import { useI18n } from "@/app/preferences";
import { InlineMarkdown } from "@/components/markdown/InlineMarkdown";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { IconButton } from "@/components/ui/icon-button";
import { Truncate } from "@/components/ui/truncate";
import { CardChoicesContext, type CardChoices } from "@/features/agent/cardChoices";
import { payloadFields, type PayloadField } from "@/features/agent/confirmationPayload";
import { HighlightedCode } from "@/features/agent/HighlightedCode";
import { NoteEditPreview } from "@/features/agent/NoteEditPreview";
import { PermissionBadge, permissionTone, type PermissionTone } from "@/features/agent/PermissionBadge";
import { SKILL_CARD_PREVIEWS } from "@/features/agent/skills/SkillCardPreviews";
import { CanvasEditPreview } from "@/features/agent/CanvasEditPreview";
import { cn } from "@/lib/utils";

/**
 * 一张确认卡 —— 聊天里的内联卡(InlineConfirmations,摆在发起它的那次工具调用下面)和右上角的全局中心
 * (ConfirmationCenter)共用这一个,两处只各自给「谁在请求」和底部的按钮。
 *
 * 此前两处各画一遍,而内联那份把四样东西塞进一行:图标 + 一整句摘要(连参数一行摘要一起)+
 * 句尾的「⚠️ 会在你的电脑上运行代码」+ 实心粉红的档次胶囊。窄对话栏里标题和警告各被挤成三行,
 * 下面再跟一坨转义过的 JSON。现在自上而下各占一行,每样东西只说一次:
 *
 *   请求方 ·························· 档次徽标     谁在请求、属于哪一档
 *   要做的事(一句人话,自然换行)                  后端的 headline:摘要去掉后果与参数摘要
 *   [!] 后果提示                                   后端的 warning,色调跟徽标同一张表
 *   参数表(短的键值两列,长的成块、还原换行、按语言高亮、默认只露前几行)
 *   按钮 / 终态那一行
 */
export function ConfirmationCard({
  item,
  eyebrow,
  actions,
  onDismiss,
  className,
}: {
  item: Confirmation;
  /** 头部左侧那一小行:谁在请求。 */
  eyebrow: string;
  /** 待决时的底部:按钮,或者只读时的一句话。 */
  actions?: React.ReactNode;
  /** 有结论的卡可以移走。 */
  onDismiss?: () => void;
  className?: string;
}) {
  const settled = item.status !== "pending";
  const tone = permissionTone(item.permission);
  const [values, setValues] = React.useState<Record<string, boolean>>(() => ({ ...(item.choices ?? {}) }));
  const choices = React.useMemo<CardChoices>(
    () => ({ values, set: (name, value) => setValues((current) => ({ ...current, [name]: value })) }),
    [values],
  );
  return (
    <CardChoicesContext.Provider value={choices}>
    <article
      data-status={item.status}
      className={cn(
        "grid min-w-0 grid-cols-[minmax(0,1fr)] gap-2.5 rounded-lg border border-border bg-panel p-3 text-ui-sm text-foreground",
        className,
      )}
    >
      <header className="flex min-w-0 items-center gap-2">
        <ShieldAlert size={14} className="shrink-0 text-muted-foreground" aria-hidden />
        <Truncate className="flex-1 text-ui-xs text-muted-foreground">{eyebrow}</Truncate>
        <PermissionBadge permission={item.permission} />
      </header>
      <p className="m-0 text-ui-sm font-semibold leading-[1.5] [overflow-wrap:anywhere]">
        <InlineMarkdown text={item.headline || item.summary} />
      </p>
      {!settled && item.warning ? <RiskNotice tone={tone} text={item.warning} /> : null}
      {!settled ? <PayloadSection item={item} /> : null}
      {settled ? <SettledLine item={item} onDismiss={onDismiss} /> : actions}
    </article>
    </CardChoicesContext.Provider>
  );
}

const NOTICE_VARIANT: Record<PermissionTone, "destructive" | "warning" | "default"> = {
  danger: "destructive",
  caution: "warning",
  neutral: "default",
};

function RiskNotice({ tone, text }: { tone: PermissionTone; text: string }) {
  // role="note":它是卡的一部分,不是一条突发的告警 —— 卡每 1.5 秒轮询一次,不该一遍遍打断读屏。
  return (
    <Alert role="note" variant={NOTICE_VARIANT[tone]} className="px-2.5 py-2">
      <TriangleAlert size={14} aria-hidden />
      <AlertDescription className="text-ui-xs leading-[1.5]">{text}</AlertDescription>
    </Alert>
  );
}

/** 终态那一行:代替按钮。失败的把原因摆出来 —— 此前批完卡就消失,执行失败只有智能体知道。 */
function SettledLine({ item, onDismiss }: { item: Confirmation; onDismiss?: () => void }) {
  const t = useI18n();
  const { icon: Icon, label, className } = SETTLED[item.status as keyof typeof SETTLED] ?? SETTLED.approved;
  return (
    <div className="flex min-w-0 items-start gap-2 border-t border-divider pt-2.5 text-ui-xs" role="status">
      <Icon size={14} className={cn("mt-[2px] shrink-0", className, item.status === "approved" && "animate-spin")} aria-hidden />
      <div className="grid min-w-0 flex-1 gap-0.5">
        <span className={cn("font-medium", className)}>{t(label)}</span>
        {item.error ? <FailureReason text={item.error} /> : null}
      </div>
      {onDismiss ? (
        <IconButton variant="ghost" size="icon-xs" className="-my-1 shrink-0" label={t("confirmDismiss")} onClick={onDismiss}>
          <X />
        </IconButton>
      ) : null}
    </div>
  );
}

/** 失败原因折叠时露出的行数与字数。够读出「哪儿出了问题」,又不至于一大段把对话栏撑满。 */
export const REASON_PREVIEW_LINES = 4;
const REASON_PREVIEW_CHARS = 280;

/**
 * 失败原因:**后端整句存下**(不再按第 500 个字截成半句),长短在这里排 —— 长的先露前几行,点开看全文。
 * 截在前面的只是显示,不是数据:「展开」之后读到的就是后端存的那一整句。
 */
export function FailureReason({ text }: { text: string }) {
  const t = useI18n();
  const [open, setOpen] = React.useState(false);
  const preview = text.split("\n").slice(0, REASON_PREVIEW_LINES).join("\n").slice(0, REASON_PREVIEW_CHARS);
  const folded = preview.length < text.length;
  return (
    <>
      <span className="whitespace-pre-wrap text-muted-foreground [overflow-wrap:anywhere]">
        {open || !folded ? text : `${preview}…`}
      </span>
      {folded ? (
        <button
          type="button"
          aria-expanded={open}
          className="w-fit cursor-pointer border-0 bg-transparent p-0 text-ui-xs text-primary hover:underline"
          onClick={() => setOpen((value) => !value)}
        >
          {open ? t("confirmCollapse") : t("confirmErrorShowAll")}
        </button>
      ) : null}
    </>
  );
}

const SETTLED = {
  approved: { icon: Loader2, label: "confirmStatusApproved", className: "text-muted-foreground" },
  executed: { icon: Check, label: "confirmStatusExecuted", className: "text-success" },
  rejected: { icon: X, label: "confirmStatusRejected", className: "text-muted-foreground" },
  failed: { icon: CircleAlert, label: "confirmStatusFailed", className: "text-destructive" },
} as const;

/**
 * 有专门画法的工具:通用参数表说不清「批了之后会变成什么样」的那几种。没列的走通用参数表。
 * 原始数据那一折所有工具都留着。
 */
const TOOL_PREVIEWS: Partial<Record<string, (payload: Record<string, unknown>, item: Confirmation) => React.ReactNode>> = {
  edit_note: (payload) => <NoteEditPreview payload={payload} />,
  //: 改 ComfyUI 画布上那张:改动清单(ADR 0042 拍板 3),清单里的节点在工作台的「助手」里能点了定位
  comfy_canvas_edit: (payload) => <CanvasEditPreview payload={payload} />,
  ...SKILL_CARD_PREVIEWS,
};

/**
 * 参数表 + 原始数据。
 *
 * 载荷不收起:这张卡是智能体写操作与执行之间唯一的闸,摘要不足以构成知情同意(一个 add_node 可能
 * 藏着一段任意本地 Python)。收起的只是**长文本的后半截**,而且写明还有多少行没显示。
 */
function PayloadSection({ item }: { item: Confirmation }) {
  const t = useI18n();
  const { tool, payload } = item;
  const preview = TOOL_PREVIEWS[tool];
  const fields = preview ? [] : payloadFields(payload);
  const raw = JSON.stringify(payload, null, 2);
  if (!preview && fields.length === 0 && raw === "{}") return null;
  return (
    <section className="grid min-w-0 gap-2" aria-label={t("confirmParams")}>
      {preview ? preview((payload ?? {}) as Record<string, unknown>, item) : null}
      {fields.length > 0 ? <FieldList fields={fields} /> : null}
      <details className="group min-w-0 text-ui-xs">
        <summary className="w-fit cursor-pointer select-none text-muted-foreground hover:text-foreground">{t("confirmPayload")}</summary>
        <HighlightedCode
          code={raw}
          language="json"
          className="mt-1.5 max-h-[220px] rounded-md border border-border bg-panel-inset p-2 text-ui-2xs"
        />
      </details>
    </section>
  );
}

function FieldList({ fields }: { fields: PayloadField[] }) {
  const values = fields.filter((one) => one.kind === "value");
  const blocks = fields.filter((one) => one.kind !== "value");
  return (
    <div className="grid min-w-0 gap-2">
      {values.length > 0 ? (
        // 键那一列按内容宽、最多四成:长键名截断,值拿剩下的并且可以换行。
        <dl className="m-0 grid min-w-0 grid-cols-[fit-content(40%)_minmax(0,1fr)] gap-x-3 gap-y-1 text-ui-xs">
          {values.map((one) => (
            <React.Fragment key={one.key}>
              <Truncate as="dt" className="font-mono text-muted-foreground">{one.key}</Truncate>
              <dd className="m-0 min-w-0 [overflow-wrap:anywhere]">{one.text === "" ? <EmptyValue /> : one.text}</dd>
            </React.Fragment>
          ))}
        </dl>
      ) : null}
      {blocks.map((one) =>
        one.kind === "group" ? (
          <div key={one.key} className="grid min-w-0 gap-1.5">
            <FieldLabel name={one.key} />
            <div className="min-w-0 border-l border-divider pl-2.5">
              <FieldList fields={one.fields} />
            </div>
          </div>
        ) : (
          <TextBlock
            key={one.key}
            name={one.key}
            text={one.text}
            language={one.kind === "data" ? "json" : one.language}
          />
        ),
      )}
    </div>
  );
}

function EmptyValue() {
  const t = useI18n();
  return <span className="text-muted-foreground">{t("confirmEmptyValue")}</span>;
}

function FieldLabel({ name, meta }: { name: string; meta?: string }) {
  return (
    <div className="flex min-w-0 items-baseline gap-2 text-ui-xs">
      <Truncate className="font-mono text-muted-foreground">{name}</Truncate>
      {meta ? <span className="shrink-0 text-ui-2xs text-muted-foreground">{meta}</span> : null}
    </div>
  );
}

/** 折叠时露出的行数。够看出「这段代码在干什么」,又不至于把按钮推出对话栏。 */
export const PREVIEW_LINES = 8;
/** 折叠时最多露出的字数 —— 一行几千字的提示词,光按行数折不住。 */
const PREVIEW_CHARS = 600;

/**
 * 一段长文本或代码:**还原真实换行**,认得出语言的高亮,认不出的按普通文字、保留换行。
 * 默认只露前 PREVIEW_LINES 行,底下一条按钮写明一共多少行。
 */
function TextBlock({ name, text, language }: { name: string; text: string; language: string | null }) {
  const t = useI18n();
  const [open, setOpen] = React.useState(false);
  const lines = text.split("\n");
  const preview = lines.slice(0, PREVIEW_LINES).join("\n").slice(0, PREVIEW_CHARS);
  const folded = preview.length < text.length;
  const shown = open || !folded ? text : preview;
  const meta = [language, t("confirmLineCount").replace("{n}", String(lines.length))].filter(Boolean).join(" · ");
  const body = cn("m-0 p-2.5 text-ui-xs leading-[1.55]", open && "max-h-[360px] overflow-auto");
  return (
    <div className="grid min-w-0 gap-1" data-field={name}>
      <FieldLabel name={name} meta={meta} />
      <div className="min-w-0 overflow-hidden rounded-md border border-border bg-panel-inset">
        {language ? (
          // 代码不折行、块内横向滚:Python 靠缩进表达结构,窄对话栏里折行之后一行代码落到行首,
          // 读的人分不清它属于哪一层。块自己滚,不会把卡撑宽。
          <HighlightedCode code={shown} language={language} className={cn(body, "overflow-x-auto whitespace-pre [word-break:normal]")} />
        ) : (
          <pre className={cn(body, "whitespace-pre-wrap font-sans [overflow-wrap:anywhere]")}>{shown}</pre>
        )}
        {folded ? (
          <button
            type="button"
            aria-expanded={open}
            className="flex w-full cursor-pointer items-center justify-center border-0 border-t border-divider bg-transparent px-2.5 py-1.5 text-ui-xs text-primary hover:bg-secondary"
            onClick={() => setOpen((value) => !value)}
          >
            {open ? t("confirmCollapse") : t("confirmShowAll").replace("{n}", String(lines.length))}
          </button>
        ) : null}
      </div>
    </div>
  );
}

/**
 * 做出了结论的卡:接口回来的那一份。留在原处显示终态,直到用户移走它或换了工作区。
 *
 * 只剩全局确认中心在用,而且只留**外部智能体执行失败**的那种(见 ConfirmationCenter):那张卡没有对话可收,
 * 原因只在这里看得到。对话里的卡不再留成一张「✓ 已执行」—— 结果收进那次工具调用的一行里(见 ToolCalls)。
 *
 * `scope` 换了就当作清空,不用 effect 去追。
 */
export function useSettledCards(scope: string) {
  const [state, setState] = React.useState<{ scope: string; cards: Confirmation[] }>({ scope, cards: [] });
  const cards = state.scope === scope ? state.cards : [];
  const remember = React.useCallback(
    (card: Confirmation) =>
      setState((prev) => ({
        scope,
        cards: [...(prev.scope === scope ? prev.cards : []).filter((one) => one.id !== card.id), card],
      })),
    [scope],
  );
  const dismiss = React.useCallback(
    (id: string) =>
      setState((prev) => ({ scope, cards: (prev.scope === scope ? prev.cards : []).filter((one) => one.id !== id) })),
    [scope],
  );
  return { cards, remember, dismiss };
}
