import React from "react";
import { useQuery } from "@tanstack/react-query";
import { Plus } from "lucide-react";

import { getModelLibrary, type ModelFile } from "@/api/client";
import { useI18n } from "@/app/preferences";
import { DEFAULT_CHOICE, declaredChoices } from "@/components/generation/parameterPanel";
import { ModelThumb, normModelName } from "@/components/generation/ModelThumb";
import { Button } from "@/components/ui/button";
import type { FieldSize } from "@/components/ui/control-size";
import { OptionPicker } from "@/components/ui/option-picker";
import type { DeclaredParameter } from "@/lib/generationCapabilities";

/** 模型库的列表在表单之间共用(同一个查询键和插件页的模型库一样),几分钟内不再现问插件。 */
const LIBRARY_STALE_MS = 5 * 60_000;
/** 下拉里每一项最多写几个触发词(全部的在选中之后那一行)。 */
const LISTED_TRIGGERS = 3;

/**
 * 生成表单里**选模型文件**的那一格(参数上写着 `x-model-folder`:大模型、LoRA、VAE……)。AI 工作台、画板、
 * 工作流节点三处共用。
 *
 * 和普通下拉同一个 OptionPicker、同一套「默认」的说法(declaredChoices),多出来的都来自这个连接的模型库:
 * 每一项一张缩略图(没有预览图就是按目录分的占位)、底模、前几个触发词(也能按它们搜)。选中带触发词的那一项,
 * 下面一行列出触发词,给了 `onUseTriggers` 就有「加进提示词」。
 *
 * 模型库读不到(连接停着、插件没有模型库)时照旧是一个能选的下拉,只是没有图和触发词 —— 不能因为看不到
 * 缩略图就选不了模型。
 */
export function ModelFilePicker({
  parameter,
  instanceId,
  value,
  onChange,
  onUseTriggers,
  className,
  size,
  ariaLabel,
}: {
  parameter: DeclaredParameter;
  instanceId: string;
  value: string;
  onChange: (next: string) => void;
  /** 把选中那一项的触发词加进提示词。不给就只列出来。 */
  onUseTriggers?: (words: string[]) => void;
  className?: string;
  size?: FieldSize;
  ariaLabel?: string;
}) {
  const t = useI18n();
  const folder = parameter.modelFolder ?? "";
  const library = useQuery({
    queryKey: ["model-library", instanceId],
    queryFn: () => getModelLibrary(instanceId),
    enabled: Boolean(instanceId && folder),
    staleTime: LIBRARY_STALE_MS,
    retry: false,
  });
  const files = React.useMemo(() => {
    const byName = new Map<string, ModelFile>();
    for (const file of library.data?.models ?? []) {
      if (file.folder === folder) byName.set(normModelName(file.name), file);
    }
    return byName;
  }, [library.data, folder]);
  const choices = declaredChoices(parameter, t);
  const known = library.isSuccess;
  const options = choices.options.map((option) => {
    const file = files.get(normModelName(option.value));
    const triggers = file?.triggers ?? [];
    const facts = [option.description, file?.family, triggers.slice(0, LISTED_TRIGGERS).join(", ")].filter(Boolean).join(" · ");
    return {
      ...option,
      description: facts || undefined,
      keywords: [file?.family ?? "", ...triggers].filter(Boolean),
      media:
        known && option.value !== DEFAULT_CHOICE ? (
          <ModelThumb compact instanceId={instanceId} model={file ?? { folder, name: option.value, has_preview: false }} />
        ) : undefined,
    };
  });
  const shown = choices.shown(value);
  const current = files.get(normModelName(shown === DEFAULT_CHOICE ? String(parameter.defaultValue ?? "") : shown));
  const triggers = current?.triggers ?? [];
  return (
    <div className="grid min-w-0 gap-1.5">
      <OptionPicker
        value={shown}
        onChange={(next) => onChange(choices.stored(next))}
        options={options}
        size={size}
        ariaLabel={ariaLabel}
        className={className}
        icon={
          known ? (
            <span aria-hidden className="grid size-5 shrink-0 overflow-hidden rounded [&>*]:size-full">
              <ModelThumb compact instanceId={instanceId} model={current ?? { folder, name: shown, has_preview: false }} />
            </span>
          ) : undefined
        }
      />
      {triggers.length > 0 && (
        <div className="flex min-w-0 flex-wrap items-center gap-1.5 text-ui-xs text-muted-foreground">
          <span>{current?.triggers_source === "tags" ? t("modelTriggersCommonTags") : t("modelTriggers")}</span>
          {triggers.slice(0, 8).map((word) => (
            <span key={word} className="rounded-full bg-secondary px-2 py-0.5 text-foreground">
              {word}
            </span>
          ))}
          {onUseTriggers && (
            <Button variant="ghost" size="sm" onClick={() => onUseTriggers(triggers)}>
              <Plus size={12} />
              {t("modelTriggersAddToPrompt")}
            </Button>
          )}
        </div>
      )}
    </div>
  );
}
