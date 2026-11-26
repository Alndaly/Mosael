import React from "react";

import { useI18n } from "@/app/preferences";
import { Truncate } from "@/components/ui/truncate";
import { HighlightedCode } from "@/features/agent/HighlightedCode";
import type { PayloadField } from "@/features/agent/confirmationPayload";
import { cn } from "@/lib/utils";

/** 折叠时露出的行数。够看出「这段在干什么」,又不至于把展开按钮推出对话栏。 */
export const PREVIEW_LINES = 8;
/** 折叠时最多露出的字数 —— 一行几千字的提示词,光按行数折不住。 */
const PREVIEW_CHARS = 600;

/**
 * 结构化参数/结果的统一摆法。
 *
 * 确认卡和工具调用明细曾经各画一遍:确认卡有参数表,工具卡却只会 `JSON.stringify` ——
 * 同一张 generate_sound 在确认时是可读的「提示词 / 歌词」,执行完就成了一块几十行的原始 JSON,
 * 输入和输出还挤在一起。把这张表抽出来,两处对同一种数据给同一种面孔。
 */
export function FieldList({ fields }: { fields: PayloadField[] }) {
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
