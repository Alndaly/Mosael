import React from "react";
import { Clapperboard } from "lucide-react";
import { useQuery } from "@tanstack/react-query";

import type { BoardItem, BoardProducerInfo, BoardRunForms } from "@/api/client";
import { getSequence } from "@/api/domains/editor";
import { useI18n } from "@/app/preferences";
import { OptionPicker } from "@/components/ui/option-picker";
import { BAR_PICKER, BoardComposerShell } from "@/features/boards/BoardComposerShell";
import { boardSequenceKey, sequenceSummary } from "@/features/boards/SequenceCell";
import { useSubmitting } from "@/features/boards/useSubmitting";
import { NodeConfigForm, useNodeFieldOptions, type ConfigSpec } from "@/features/nodeForms/NodeConfigForm";
import { cn } from "@/lib/utils";

type Form = BoardRunForms["sequence_export"];

/** 底栏上的两枚芯片:分辨率、画质。「AI 生成」标识进「参数」。 */
const BAR_FIELDS = ["resolution", "quality"] as const;

/**
 * 时间线格的导出面板(ADR 0030 §4):**按需打开** —— 操作条上点「导出」才挂(选中时间线格多半是要剪、要排,
 * 不是要导)。点发送起一次正常的导出任务(工作流节点 `export_sequence` 的同一个执行器),成片落成右边一格视频。
 *
 * 和画板上别的面板同一个壳;字段的名字、说明、选项、缺省都读后端发的那一份声明(节点 `export_sequence` 的字段,
 * 少了时间线):分辨率、画质和剪辑页的导出对话框是同一组取值。
 */
export function SequenceExportComposer({
  item,
  producer,
  workspaceId,
  busy,
  onFormChange,
  onRun,
}: {
  item: BoardItem;
  /** 导出的声明(后端 GET /api/boards/producers 的 sequence_export)。undefined = 清单还在路上。 */
  producer: BoardProducerInfo | undefined;
  workspaceId: string;
  busy: boolean;
  onFormChange: (form: NonNullable<BoardItem["form"]>) => void;
  onRun: (form: Form) => Promise<unknown>;
}) {
  const t = useI18n();
  const specs = React.useMemo(() => (producer?.config ?? {}) as Record<string, ConfigSpec>, [producer]);
  const config = React.useMemo(() => (item.form?.config ?? {}) as Record<string, unknown>, [item.form?.config]);
  const fieldOptions = useNodeFieldOptions({ specs, config, workspaceId, nodeType: producer?.type ?? "" });
  const { submitting, run } = useSubmitting();
  const working = submitting || busy;
  const sequenceId = item.sequence_id ?? "";
  const sequence = useQuery({
    queryKey: boardSequenceKey(sequenceId),
    queryFn: () => getSequence(sequenceId),
    enabled: Boolean(sequenceId),
    retry: false,
  });
  const summary = sequenceSummary(sequence.data);
  const empty = summary.clips === 0;

  const setConfig = (key: string, value: unknown) => onFormChange({ ...item.form, config: { ...config, [key]: value } });
  const patchConfig = (patch: Record<string, unknown>) => onFormChange({ ...item.form, config: { ...config, ...patch } });
  const label = (key: string) => String(specs[key]?.label || key);
  //: 只发导出自己的那几项(服务端的表单不收不认识的键)。
  const send = () => {
    if (!producer || empty || working) return;
    const own = Object.fromEntries(Object.entries(config).filter(([key]) => key in specs)) as Form["config"];
    run(() => onRun({ config: own }));
  };

  const chip = (key: string) => {
    const spec = specs[key];
    if (!spec) return null;
    const options = (spec.options ?? []).map((one) => ({ value: String(one), label: spec.option_labels?.[String(one)] ?? String(one) }));
    return (
      <span key={key} data-field-key={key} className="flex min-w-0 max-w-[min(15rem,45%)] shrink" title={label(key)}>
        <OptionPicker
          size="sm"
          ariaLabel={label(key)}
          value={String(config[key] ?? spec.default ?? "")}
          onChange={(next) => setConfig(key, next)}
          options={options}
          placeholder={label(key)}
          className={cn(BAR_PICKER, "max-w-full text-foreground")}
          contentClassName="max-w-[min(360px,calc(100vw-16px))]"
        />
      </span>
    );
  };
  const rest = Object.entries(specs).filter(([key]) => !(BAR_FIELDS as readonly string[]).includes(key));

  return (
    <BoardComposerShell
      nodeId={item.id}
      name="sequence-export"
      bar={producer ? <>{BAR_FIELDS.map(chip)}</> : null}
      settings={
        producer && rest.length > 0
          ? {
              content: (
                <NodeConfigForm
                  compact
                  fields={rest}
                  config={config}
                  workspaceId={workspaceId}
                  variables={[]}
                  fieldOptions={fieldOptions}
                  onSetConfig={setConfig}
                  onTypeConfig={setConfig}
                  onPatchConfig={(_owner, patch) => patchConfig(patch)}
                />
              ),
            }
          : null
      }
      send={
        producer
          ? {
              label: t(item.run?.status === "succeeded" ? "boardSequenceExportAgain" : "boardSequenceExport"),
              hint: empty ? t("boardSequenceExportEmpty") : t("boardSequenceExportHint"),
              onSend: send,
              disabled: empty,
              working,
            }
          : null
      }
    >
      <div data-sequence-export-summary="" className="flex min-w-0 items-center gap-2.5 px-1 py-1">
        <div className="grid h-10 w-10 shrink-0 place-items-center rounded-md border border-border bg-secondary/40 text-muted-foreground">
          <Clapperboard size={16} strokeWidth={1.4} />
        </div>
        <div className="grid min-w-0 flex-1 gap-0.5">
          <span className="truncate text-ui-sm text-foreground" title={item.text}>{item.text || t("boardKindSequence")}</span>
          <span className="truncate text-ui-2xs tabular-nums text-muted-foreground">
            {empty
              ? t("boardSequenceExportEmpty")
              : t("boardSequenceExportSummary")
                  .replace("{clips}", String(summary.clips))
                  .replace("{seconds}", summary.seconds.toFixed(1))
                  .replace("{size}", summary.size)}
          </span>
        </div>
      </div>
    </BoardComposerShell>
  );
}
