import React from "react";
import { Eye } from "lucide-react";

import type { GenerationOption, WorkflowApp } from "@/api/client";
import { useI18n, usePreferences } from "@/app/preferences";
import { InlineMarkdown } from "@/components/markdown/InlineMarkdown";
import { DeclaredParameterControl, PARAMETER_CONTROL_CLASS, ParameterField } from "@/components/generation/parameterPanel";
import { Input } from "@/components/ui/input";
import { OptionPicker } from "@/components/ui/option-picker";
import { Textarea } from "@/components/ui/textarea";
import { Truncate } from "@/components/ui/truncate";
import { appFormFields, type AppField } from "@/lib/appFormFields";
import { defaultDraft, previewOption, type FormDraft } from "@/features/plugins/workflowAppForm";
import {
  appForm,
  declaredParameters,
  promptMode,
  sizeOptions,
  sourceLabels,
  sourceLimit,
} from "@/lib/generationCapabilities";
import { ROLE_COPY, slotColumns, type SourceRole } from "@/lib/sourceFrames";

type Translate = ReturnType<typeof useI18n>;

/**
 * 「预览」:用的人看到的那张表 —— 按草稿拼一份和生成目录同形的描述符(workflowAppForm.previewOption),交给生成面板同一组读法和
 * 控件画出来,能试着填、不存。表单还空着时,画的是**现在**用的人看到的那张(缺省的应用:全部能填的项),并说清楚这一点。
 */
export function PreviewPanel({ instanceId, data, draft }: { instanceId: string; data: WorkflowApp; draft: FormDraft }) {
  const t = useI18n();
  //: 作者没起名字的那几格用插件交回的名字:一句或一张语言表,按界面语言挑一句(见 lib/pickLabel)
  const { locale } = usePreferences();
  const empty = draft.items.length === 0;
  const shown = React.useMemo(() => (empty ? defaultDraft(data) : draft), [empty, data, draft]);
  const option = React.useMemo(() => previewOption(data, shown, instanceId, locale), [data, shown, instanceId, locale]);
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

/**
 * 预览本身:**表上的每一项,按表上的顺序** —— 哪一格、第几格都由 lib/appFormFields 说了算,和生成面板同一份判据
 * (此前这里按自己分好的类摆:提示词 → 反向提示词 → 素材槽 → 尺寸 → 张数 → 种子 → 参数,于是作者在中间跨类拖动
 * ——把「参考图」拖到「放大倍数」下面——预览里什么都看不出变化)。用的人把值填着看看,不存:
 * 每一格的值只在这个组件的 `values` 里,真实配置在右栏那一份。
 */
function AppPreview({ option, title, note }: { option: GenerationOption; title: string; note: string }) {
  const t = useI18n();
  const [values, setValues] = React.useState<Record<string, string>>({});
  const set = (key: string, value: string) => setValues((current) => ({ ...current, [key]: value }));
  const mode = promptMode(option);
  const sizes = sizeOptions(option);
  const parameters = new Map(declaredParameters(option).map((parameter) => [parameter.key, parameter]));
  //: 表上的顺序,就是描述符 `form` 的顺序(previewOption 照草稿拼的)—— 表上没有的格子这里也不画。
  const fields = appFormFields(option, appForm(option)?.items ?? []);
  const control = (field: AppField) => {
    if (field.kind === "prompt") {
      return (
        <ParameterField label={field.label || t("genPromptLabel")}>
          <Textarea className="min-h-20 text-foreground" value={values[field.key] ?? ""}
                    onChange={(event) => set(field.key, event.target.value)} />
        </ParameterField>
      );
    }
    if (field.kind === "negative_prompt") {
      return (
        <ParameterField label={field.label || t("genNegativePrompt")}>
          <Textarea className="min-h-14 text-foreground" value={values[field.key] ?? ""}
                    onChange={(event) => set(field.key, event.target.value)} />
        </ParameterField>
      );
    }
    if (field.kind === "source") {
      const role = field.role as SourceRole;
      return <PreviewSlots role={role} t={t} names={sourceLabels(option, role)} count={sourceLimit(option, role)} />;
    }
    if (field.kind === "size") {
      /* 描述符没给可选值(目录没声明)就没有可挑的,和生成面板那边的尺寸栏一个判据 */
      if (sizes.length === 0) return null;
      return (
        <ParameterField label={field.label || t("genSize")}>
          <OptionPicker className={PARAMETER_CONTROL_CLASS} value={values[field.key] ?? sizes[0]}
                        onChange={(next) => set(field.key, next)} options={sizes.map((one) => ({ value: one, label: one }))} />
        </ParameterField>
      );
    }
    if (field.kind === "num_images") {
      return (
        <ParameterField label={field.label || t("genRuns")}>
          <Input className={PARAMETER_CONTROL_CLASS} type="number" min={1} max={4} value={values[field.key] ?? "1"}
                 onChange={(event) => set(field.key, event.target.value)} />
        </ParameterField>
      );
    }
    if (field.kind === "seed") {
      return (
        <ParameterField label={field.label || t("genSeed")}>
          <Input className={PARAMETER_CONTROL_CLASS} type="number" placeholder="auto" value={values[field.key] ?? ""}
                 onChange={(event) => set(field.key, event.target.value)} />
        </ParameterField>
      );
    }
    //: 描述符声明的参数:按 parameterKey 查表,认不出就不画(和面板那边的 declaredField 一样)。
    const parameter = field.parameterKey ? parameters.get(field.parameterKey) : undefined;
    if (!parameter) return null;
    return (
      <ParameterField label={parameter.label} title={parameter.description || undefined}>
        <DeclaredParameterControl parameter={parameter} value={values[field.key] ?? ""}
                                  onChange={(next) => set(field.key, next)} />
      </ParameterField>
    );
  };
  return (
    <div className="grid gap-3" data-app-preview>
      <div className="grid gap-0.5">
        {/* 同上:表单名长度不由我们定,外面这一层得能收缩,否则 `Truncate` 拿不到宽度。 */}
        <span className="min-w-0 text-ui-md font-semibold text-foreground"><Truncate>{title}</Truncate></span>
        {note.trim() && (
          <span className="text-ui-xs leading-relaxed text-muted-foreground"><InlineMarkdown text={note} /></span>
        )}
      </div>
      {/* 这个模型不收提示词:表上没有提示词那一格(它就是「照工作流里存的那句跑」),说清楚这件事 */}
      {mode === "none" ? (
        <p className="m-0 text-ui-xs leading-relaxed text-muted-foreground">{t("workflowAppPromptNone")}</p>
      ) : null}
      {fields.map((field) => {
        const drawn = control(field);
        return drawn ? (
          <div key={field.key} data-app-field={field.key}>
            {drawn}
          </div>
        ) : null;
      })}
    </div>
  );
}

/**
 * 一个角色的槽位:几格虚线框,每格写着它的名字(`source_labels`)。**和真控件同一套装法** ——
 * 一行铺满、最多三份(`sourceFrames.slotColumns`),格子的高度、圆角、虚线也和那边一致。
 * 此前这里是 `auto-fill minmax(88px,1fr)`:一份素材缩成一个小方块,而用的人真正看到的是铺满整行的那一格
 * (维护者:「右侧这个预览 同一行应该撑满宽度」)。预览说的就是"看到的就是这样",两处不能各画一套。
 */
function PreviewSlots({ role, names, count, t }: { role: SourceRole; names: string[]; count: number; t: Translate }) {
  const label = t(ROLE_COPY[role].label);
  const slots = Math.max(count, 1);
  return (
    <div className="grid gap-1.5 text-ui-xs font-semibold text-muted-foreground">
      <span>{label}</span>
      <ul aria-label={label} className="m-0 grid list-none gap-1.5 p-0" style={{ gridTemplateColumns: slotColumns(slots) }}>
        {Array.from({ length: slots }, (_, index) => (
          <li key={index}
              className="grid h-[68px] place-items-center overflow-hidden rounded-lg border border-dashed border-border bg-muted/40 px-1.5">
            <Truncate className="max-w-full text-ui-xs font-medium text-foreground">{names[index] || `${label} ${index + 1}`}</Truncate>
          </li>
        ))}
      </ul>
    </div>
  );
}
