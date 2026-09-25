import React from "react";
import { Braces, Pencil } from "lucide-react";

import type { PluginField } from "@/api/client";
import { useI18n } from "@/app/preferences";
import { CodeEditor } from "@/components/app/code-editor";
import { ModalShell } from "@/components/app/modals";
import { InlineMarkdown } from "@/components/markdown/InlineMarkdown";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

/**
 * 插件清单里 `type: "json"` / `type: "code"` 的配置项:**一段代码**,不是一个多行文本框。
 *
 * 此前 ComfyUI 的「API 模板」是一个右栏里 200px 宽的 textarea,占位符就是标签本身,粘进去一份几百行
 * 的 JSON 只看得见第一行,少一个逗号要等插件跑起来才报。现在:
 *
 * - 连接卡片上那一行只放**摘要**(未设置 / 已填写 · 42 行 · 3 个占位符)和「编辑」,编辑在一个大弹窗里
 *   (用户说的:「有必要的地方可以通过弹窗解决」)—— 卡片那一栏装不下一段代码;
 * - 编辑器就是全应用那一个(CodeMirror,工作流的 JSON 字段和代码节点用的同一个),有行号、高亮;
 * - `json` 边敲边校验,**错在第几行第几列**当场说,错着的时候保存按不下去(后端保存前还会再查一遍)。
 *
 * 值照旧是字符串(插件拿到的就是它粘进去的原文),所以没有数据迁移。
 */

export const CODE_FIELD_TYPES = new Set(["json", "code"]);

export function isCodeField(field: PluginField): boolean {
  return CODE_FIELD_TYPES.has(field.type ?? "");
}

export interface JsonProblem {
  line: number;
  column: number;
  detail: string;
}

/**
 * 这段 JSON 哪里不对;没问题(或者是空的)回 null。
 *
 * `JSON.parse` 的报错各家引擎说法不一:V8 新版带「(line 3 column 1)」,老版只有「at position 42」,
 * 都认;都没有就只给原话(行列按 1:1)。
 */
export function jsonProblem(text: string): JsonProblem | null {
  if (!text.trim()) return null;
  try {
    JSON.parse(text);
    return null;
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    const lineColumn = /line (\d+) column (\d+)/i.exec(message);
    const detail = message.replace(/\s*\(line \d+ column \d+\)/i, "").replace(/ in JSON at position \d+/i, "");
    if (lineColumn) return { line: Number(lineColumn[1]), column: Number(lineColumn[2]), detail };
    const position = /position (\d+)/i.exec(message);
    if (position) {
      const before = text.slice(0, Number(position[1]));
      const lines = before.split("\n");
      return { line: lines.length, column: lines[lines.length - 1].length + 1, detail };
    }
    return { line: 1, column: 1, detail };
  }
}

/** 摘要里说的那几样:几行、几个 `{{占位符}}`(模板这类配置的要点就是它们)。 */
export function codeSummary(text: string): { lines: number; placeholders: number } {
  const trimmed = text.trim();
  if (!trimmed) return { lines: 0, placeholders: 0 };
  const placeholders = new Set(trimmed.match(/\{\{\s*\w+\s*\}\}/g) ?? []);
  return { lines: trimmed.split("\n").length, placeholders: placeholders.size };
}

/** 编辑器本体 + 校验那一行。新建连接的弹窗里直接用它,连接卡片上包在弹窗里用。 */
export function CodeFieldEditor({
  field,
  value,
  onChange,
  minHeight = 160,
  maxHeight = 360,
  autoFocus,
}: {
  field: PluginField;
  value: string;
  onChange: (value: string) => void;
  minHeight?: number;
  maxHeight?: number;
  autoFocus?: boolean;
}) {
  const t = useI18n();
  const language = field.type === "json" ? "json" : field.language || "text";
  const problem = field.type === "json" ? jsonProblem(value) : null;
  return (
    <div className="grid min-w-0 gap-1.5">
      <CodeEditor
        value={value}
        onChange={onChange}
        language={language}
        minHeight={minHeight}
        maxHeight={maxHeight}
        autoFocus={autoFocus}
        placeholder={field.type === "json" ? "{ }" : undefined}
      />
      {problem && (
        <p role="alert" className="m-0 text-ui-xs leading-[1.5] text-destructive">
          {t("pluginJsonError")
            .replace("{line}", String(problem.line))
            .replace("{column}", String(problem.column))
            .replace("{detail}", problem.detail)}
        </p>
      )}
    </div>
  );
}

/**
 * 连接卡片上那一行的控件:摘要 + 「编辑」。点开是一个大弹窗,改完「保存」才发出去 ——
 * 这一格的值是一整段代码,逐字提交(失焦就存)会把改到一半的 JSON 存进去。
 */
export function CodeConfigControl({
  field,
  value,
  onSave,
}: {
  field: PluginField;
  value: string;
  /** 存上去。失败时抛(后端的校验错误),弹窗留着并把原因显示出来。 */
  onSave: (value: string) => Promise<unknown>;
}) {
  const t = useI18n();
  const [open, setOpen] = React.useState(false);
  const [draft, setDraft] = React.useState(value);
  const [saving, setSaving] = React.useState(false);
  const [serverError, setServerError] = React.useState("");
  const summary = codeSummary(value);
  const problem = field.type === "json" ? jsonProblem(draft) : null;

  const start = () => {
    setDraft(value);
    setServerError("");
    setOpen(true);
  };
  const save = async () => {
    setSaving(true);
    setServerError("");
    try {
      await onSave(draft);
      setOpen(false);
    } catch (error) {
      setServerError(error instanceof Error ? error.message : String(error));
    } finally {
      setSaving(false);
    }
  };
  const format = () => {
    try {
      setDraft(JSON.stringify(JSON.parse(draft), null, 2));
    } catch {
      // 不合法的 JSON 没法格式化;编辑器下面那一行已经在说哪里不对
    }
  };

  return (
    <>
      <div className="flex min-w-0 items-center gap-2">
        <span className={cn("min-w-0 truncate text-ui-sm", summary.lines ? "text-foreground" : "text-muted-foreground")}>
          {summary.lines
            ? [
                t("pluginCodeFilled").replace("{lines}", String(summary.lines)),
                summary.placeholders ? t("pluginCodePlaceholders").replace("{n}", String(summary.placeholders)) : "",
              ]
                .filter(Boolean)
                .join(" · ")
            : t("pluginCodeEmpty")}
        </span>
        <Button variant="outline" onClick={start} aria-label={t("pluginCodeEditTitle").replace("{label}", field.label)}>
          <Pencil size={13} />
          {t("pluginCodeEdit")}
        </Button>
      </div>
      <ModalShell
        open={open}
        onOpenChange={(next) => !saving && setOpen(next)}
        title={t("pluginCodeEditTitle").replace("{label}", field.label)}
        className="w-[760px] max-w-[calc(100vw-32px)]"
        footer={
          <div className="flex w-full items-center gap-2">
            {field.type === "json" && (
              <Button variant="ghost" disabled={saving || !draft.trim() || Boolean(problem)} onClick={format}>
                <Braces size={13} />
                {t("pluginCodeFormat")}
              </Button>
            )}
            <Button variant="ghost" disabled={saving || !draft} onClick={() => setDraft("")}>
              {t("pluginCodeClear")}
            </Button>
            <span className="flex-1" />
            <Button variant="outline" disabled={saving} onClick={() => setOpen(false)}>
              {t("cancel")}
            </Button>
            <Button loading={saving} disabled={Boolean(problem) || draft === value} onClick={() => void save()}>
              {t("save")}
            </Button>
          </div>
        }
      >
        <div className="grid gap-3">
          {field.help && (
            <p className="m-0 text-ui-sm leading-[1.6] text-muted-foreground">
              <InlineMarkdown text={field.help} />
            </p>
          )}
          {serverError && (
            <p role="alert" className="m-0 text-ui-xs leading-[1.5] text-destructive">
              {serverError}
            </p>
          )}
          <CodeFieldEditor field={field} value={draft} onChange={setDraft} minHeight={320} maxHeight={560} autoFocus />
        </div>
      </ModalShell>
    </>
  );
}
