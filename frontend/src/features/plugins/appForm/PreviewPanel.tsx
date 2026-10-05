import React from "react";
import { Eye } from "lucide-react";

import type { GenerationOption, WorkflowApp } from "@/api/client";
import { useI18n } from "@/app/preferences";
import { InlineMarkdown } from "@/components/markdown/InlineMarkdown";
import { DeclaredParameterControl, PARAMETER_CONTROL_CLASS, ParameterField } from "@/components/generation/parameterPanel";
import { Input } from "@/components/ui/input";
import { OptionPicker } from "@/components/ui/option-picker";
import { Textarea } from "@/components/ui/textarea";
import { Truncate } from "@/components/ui/truncate";
import { defaultDraft, previewOption, type AppDraft } from "@/features/plugins/workflowAppForm";
import {
  declaredParameters,
  promptMode,
  sizeOptions,
  sourceLabels,
  sourceLimit,
  supportsParameter,
} from "@/lib/generationCapabilities";
import { ROLE_COPY, SOURCE_ROLES, type SourceRole } from "@/lib/sourceFrames";

type Translate = ReturnType<typeof useI18n>;

/**
 * 「预览」:用的人看到的那张表 —— 按草稿拼一份和生成目录同形的描述符(workflowAppForm.previewOption),交给生成面板同一组读法和
 * 控件画出来,能试着填、不存。表单还空着时,画的是**现在**用的人看到的那张(缺省的应用:全部能填的项),并说清楚这一点。
 */
export function PreviewPanel({ instanceId, data, draft }: { instanceId: string; data: WorkflowApp; draft: AppDraft }) {
  const t = useI18n();
  const empty = draft.items.length === 0;
  const shown = React.useMemo(() => (empty ? defaultDraft(data) : draft), [empty, data, draft]);
  const option = React.useMemo(() => previewOption(data, shown, instanceId), [data, shown, instanceId]);
  return (
    <aside aria-label={t("workflowAppPreview")} className="grid min-w-0 content-start gap-3" data-app-zone="preview">
      <div className="grid gap-0.5">
        <h4 className="m-0 flex items-center gap-1.5 text-ui-sm font-semibold text-foreground">
          <Eye size={14} aria-hidden />
          {t("workflowAppPreview")}
        </h4>
        <p className="m-0 text-ui-xs leading-relaxed text-muted-foreground">{t("workflowAppPreviewHint")}</p>
      </div>
      {empty && (
        <p className="m-0 rounded-lg bg-secondary/60 px-3 py-2 text-ui-xs leading-relaxed text-muted-foreground" data-app-preview-default="">
          {t("workflowAppPreviewDefault").replace("{n}", String((data.items ?? []).length))}
        </p>
      )}
      <div className="grid gap-3 rounded-xl border border-border bg-panel p-3">
        <AppPreview option={option} title={draft.title.trim() || data.path.replace(/\.json$/i, "")} note={draft.description} />
      </div>
    </aside>
  );
}

/** 预览本身:提示词框、素材槽位(每格的名字)、尺寸、张数、种子、参数表。值只在这里改着看,不存。 */
function AppPreview({ option, title, note }: { option: GenerationOption; title: string; note: string }) {
  const t = useI18n();
  const [values, setValues] = React.useState<Record<string, string>>({});
  const set = (key: string, value: string) => setValues((current) => ({ ...current, [key]: value }));
  const mode = promptMode(option);
  const roles = SOURCE_ROLES.filter((role) => supportsParameter(option, role));
  const sizes = sizeOptions(option);
  return (
    <div className="grid gap-3" data-app-preview>
      <div className="grid gap-0.5">
        <span className="text-ui-md font-semibold text-foreground"><Truncate>{title}</Truncate></span>
        {note.trim() && (
          <span className="text-ui-xs leading-relaxed text-muted-foreground"><InlineMarkdown text={note} /></span>
        )}
      </div>
      {mode === "none" ? (
        <p className="m-0 text-ui-xs leading-relaxed text-muted-foreground">{t("workflowAppPromptNone")}</p>
      ) : (
        <ParameterField label={t("genPromptLabel")}>
          <Textarea className="min-h-20 rounded-lg border-border bg-field text-ui-sm" value={values.prompt ?? ""}
                    onChange={(event) => set("prompt", event.target.value)} />
        </ParameterField>
      )}
      {supportsParameter(option, "negative_prompt") && (
        <ParameterField label={t("genNegativePrompt")}>
          <Textarea className="min-h-14 rounded-lg border-border bg-field text-ui-sm" value={values.negative ?? ""}
                    onChange={(event) => set("negative", event.target.value)} />
        </ParameterField>
      )}
      {roles.map((role) => (
        <PreviewSlots key={role} role={role} t={t} names={sourceLabels(option, role)} count={sourceLimit(option, role)} />
      ))}
      {sizes.length > 0 && (
        <ParameterField label={t("genSize")}>
          <OptionPicker className={PARAMETER_CONTROL_CLASS} value={values.size ?? sizes[0]}
                        onChange={(next) => set("size", next)} options={sizes.map((one) => ({ value: one, label: one }))} />
        </ParameterField>
      )}
      {supportsParameter(option, "num_images") && (
        <ParameterField label={t("genRuns")}>
          <Input className={PARAMETER_CONTROL_CLASS} type="number" min={1} max={4} value={values.runs ?? "1"}
                 onChange={(event) => set("runs", event.target.value)} />
        </ParameterField>
      )}
      {supportsParameter(option, "seed") && (
        <ParameterField label={t("genSeed")}>
          <Input className={PARAMETER_CONTROL_CLASS} type="number" placeholder="auto" value={values.seed ?? ""}
                 onChange={(event) => set("seed", event.target.value)} />
        </ParameterField>
      )}
      {declaredParameters(option).map((parameter) => (
        <ParameterField key={parameter.key} label={parameter.label} title={parameter.description || undefined}>
          <DeclaredParameterControl parameter={parameter} value={values[parameter.key] ?? ""}
                                    onChange={(next) => set(parameter.key, next)} />
        </ParameterField>
      ))}
    </div>
  );
}

/** 一个角色的槽位:几格虚线框,每格写着它的名字(`source_labels`)。 */
function PreviewSlots({ role, names, count, t }: { role: SourceRole; names: string[]; count: number; t: Translate }) {
  const label = t(ROLE_COPY[role].label);
  return (
    <div className="grid gap-1.5 text-ui-xs font-semibold text-muted-foreground">
      <span>{label}</span>
      <ul aria-label={label} className="m-0 grid list-none grid-cols-[repeat(auto-fill,minmax(88px,1fr))] gap-1.5 p-0">
        {Array.from({ length: count }, (_, index) => (
          <li key={index} className="grid h-14 place-items-center rounded-lg border border-dashed border-border bg-muted/40 px-1.5">
            <Truncate className="max-w-full text-ui-xs font-medium text-foreground">{names[index] || `${label} ${index + 1}`}</Truncate>
          </li>
        ))}
      </ul>
    </div>
  );
}
