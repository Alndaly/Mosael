import { declaredChoices, PARAMETER_CONTROL_CLASS } from "@/components/generation/parameterPanel";
import { useI18n } from "@/app/preferences";
import { RefCombobox } from "@/features/nodeForms/RefCombobox";
import { RefEditor } from "@/features/nodeForms/RefEditor";
import type { DeclaredParameter } from "@/lib/generationCapabilities";

/**
 * 工作流里的模型声明参数:有上游清单,所以下拉和文本都走引用感知的那一套。
 * AI 工作台 / 画板没有上游输出,继续用 components/generation 的原生控件。
 */
export function ReferenceParameterControl({
  parameter,
  value,
  variables,
  onChange,
}: {
  parameter: DeclaredParameter;
  value: string;
  variables: readonly string[];
  onChange: (next: string, typing: boolean) => void;
}) {
  const t = useI18n();
  if (parameter.type === "boolean" || parameter.options.length > 0) {
    const choices = declaredChoices(parameter, t);
    return (
      <RefCombobox
        value={choices.shown(value)}
        options={choices.options}
        variables={variables}
        literal={false}
        className={PARAMETER_CONTROL_CLASS}
        onValueChange={(next) => onChange(choices.stored(next), false)}
      />
    );
  }
  return (
    <RefEditor
      rows={parameter.multiline ? 4 : 1}
      value={value}
      variables={variables}
      label={parameter.label}
      onChange={(next) => onChange(next, true)}
    />
  );
}
