import type React from "react";

import type { useI18n } from "@/app/preferences";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { JsonField } from "@/features/nodeForms/JsonField";
import { FIELD_BOX } from "@/features/nodeForms/NodeConfigForm";
import { RefEditor } from "@/features/nodeForms/RefEditor";
import type { SetGraphOptions } from "@/features/workflows/workflowGraphStore";

//: 节点检查器里「大模型」节点的专区:预设在参数档;输出格式、JSON Schema、采样参数、Schema 名称和严格与否在高级档。
//: 输出格式此前在高级里(维护者一度以为没有 JSON 模式)、一度被挪去参数档(970ab0e58),维护者拍板:**收回高级** —
//: 「要一份 JSON、下游按字段取」是微调,不该占基础档第一眼;挪去参数那阵还连带把「高级」tab 弄丢了(llm 的高级项
//: 全在专区里、被剔出通用 advancedSpecs,areas 因此不含 advanced),这里一并修好(见 NodeInspector 的 areas)。
//: 两块都是**返回元素的函数,不是组件** —— 检查器直接调,React 树和拆出来之前一样。

//: 大模型节点里由专区自己渲染的配置项,不走通用字段列表。
export const LLM_SPECIAL_CONFIG_KEYS = new Set([
  "preset",
  "temperature",
  "top_p",
  "max_tokens",
  "frequency_penalty",
  "presence_penalty",
  "seed",
  "stop",
  "response_format",
  "json_schema_name",
  "json_schema",
  "json_schema_strict",
]);

interface LlmSectionProps {
  t: ReturnType<typeof useI18n>;
  nodeId: string;
  config: Record<string, unknown>;
  variables: string[];
  setConfig: (key: string, value: unknown, options?: SetGraphOptions) => void;
  setTextConfig: (key: string) => (event: React.ChangeEvent<HTMLInputElement>) => void;
  typeConfig: (key: string) => (value: unknown) => void;
  responseFormat: string;
}

/** 参数档:预设。「输出格式 / JSON Schema」按维护者的决定收在高级档(llmAdvancedSection)—— JSON 是给
 *  下游按字段取的微调,不该占基础档的第一眼;采样参数、Schema 名称、严格与否本来就在高级。 */
export function llmMainSection({ t, config, setConfig }: LlmSectionProps): React.ReactElement {
  return (
    <div // **不套框。** 检查器本身已经是一张卡片,里面再画一圈边框就是框中框,而那圈线不表示
      // 任何东西 —— 它只是让内容离两边更远、可读宽度更窄。
      className="grid gap-3">
      <div className={FIELD_BOX}>
        <span>{t("wfLlmPreset")}</span>
        <Select
          value={(config.preset as string) || "balanced"}
          onValueChange={(next) => setConfig("preset", next)}
        >
          <SelectTrigger>
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="precise">{t("wfPresetPrecise")}</SelectItem>
            <SelectItem value="balanced">{t("wfPresetBalanced")}</SelectItem>
            <SelectItem value="creative">{t("wfPresetCreative")}</SelectItem>
          </SelectContent>
        </Select>
        <small>
          {config.preset === "precise"
            ? t("wfPresetPreciseHint")
            : config.preset === "creative"
              ? t("wfPresetCreativeHint")
              : t("wfPresetBalancedHint")}
        </small>
      </div>
    </div>
  );
}

/** 高级档:输出格式、JSON Schema、采样参数、停止词、Schema 名称和严格与否。 */
export function llmAdvancedSection({
  t,
  nodeId,
  config,
  variables,
  setConfig,
  setTextConfig,
  typeConfig,
  responseFormat,
}: LlmSectionProps): React.ReactElement {
  return (
    <div className="grid gap-3">
      {/* 输出格式 + JSON Schema 收在高级(维护者决定):JSON 模式是给下游按字段取的微调。放高级第一项,
          「要 JSON、按 Schema」这件事一眼找得到,又不占基础档。 */}
      <div className={FIELD_BOX} data-llm-response-format="">
        <span>{t("wfLlmResponseFormat")}</span>
        <Select value={responseFormat} onValueChange={(next) => setConfig("response_format", next)}>
          <SelectTrigger>
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="text">{t("wfLlmResponseText")}</SelectItem>
            <SelectItem value="json_object">{t("wfLlmResponseJsonObject")}</SelectItem>
            <SelectItem value="json_schema">{t("wfLlmResponseJsonSchema")}</SelectItem>
          </SelectContent>
        </Select>
        <small>
          {responseFormat === "json_schema"
            ? t("wfLlmResponseSchemaHint")
            : responseFormat === "json_object"
              ? t("wfLlmResponseJsonHint").replace("{ref}", `{{${nodeId}.json}}`)
              : t("wfLlmResponseTextHint")}
        </small>
      </div>
      {responseFormat === "json_schema" && (
        <div className={FIELD_BOX}>
          <span>{t("wfLlmJsonSchema")}</span>
          <JsonField
            value={config.json_schema ?? { type: "object", properties: {} }}
            onChange={(parsed) => setConfig("json_schema", parsed)}
          />
        </div>
      )}
      <div className="grid grid-cols-2 gap-2 max-[1180px]:grid-cols-1">
        <div className={FIELD_BOX}>
          <span>{t("wfLlmTemperature")}</span>
          <Input
            type="number"
            min={0}
            max={2}
            step="0.1"
            value={String(config.temperature ?? "")}
            placeholder={t("wfLlmTemperaturePlaceholder")}
            onChange={setTextConfig("temperature")}
          />
        </div>
        <div className={FIELD_BOX}>
          <span>{t("wfLlmTopP")}</span>
          <Input
            type="number"
            min={0}
            max={1}
            step="0.05"
            value={String(config.top_p ?? "")}
            placeholder="0-1"
            onChange={setTextConfig("top_p")}
          />
        </div>
        <div className={FIELD_BOX}>
          <span>{t("wfLlmMaxTokens")}</span>
          <Input
            type="number"
            min={1}
            step="1"
            value={String(config.max_tokens ?? "")}
            placeholder={t("wfLlmBlankDefault")}
            onChange={setTextConfig("max_tokens")}
          />
        </div>
        <div className={FIELD_BOX}>
          <span>{t("wfLlmSeed")}</span>
          <Input
            type="number"
            step="1"
            value={String(config.seed ?? "")}
            placeholder={t("wfLlmBlankDefault")}
            onChange={setTextConfig("seed")}
          />
        </div>
        <div className={FIELD_BOX}>
          <span>{t("wfLlmFrequencyPenalty")}</span>
          <Input
            type="number"
            min={-2}
            max={2}
            step="0.1"
            value={String(config.frequency_penalty ?? "")}
            placeholder={t("wfRangeMinus2To2")}
            onChange={setTextConfig("frequency_penalty")}
          />
        </div>
        <div className={FIELD_BOX}>
          <span>{t("wfLlmPresencePenalty")}</span>
          <Input
            type="number"
            min={-2}
            max={2}
            step="0.1"
            value={String(config.presence_penalty ?? "")}
            placeholder={t("wfRangeMinus2To2")}
            onChange={setTextConfig("presence_penalty")}
          />
        </div>
      </div>
      <div className={FIELD_BOX}>
        <span>{t("wfLlmStop")}</span>
        <RefEditor
          rows={2}
          value={String(config.stop ?? "")}
          onChange={typeConfig("stop")}
          variables={variables}
          label={t("wfLlmStop")}
        />
        <small>{t("wfLlmStopHint")}</small>
      </div>
      {responseFormat === "json_schema" && (
        <>
          <div className={FIELD_BOX}>
            <span>{t("wfLlmJsonSchemaName")}</span>
            <Input
              value={String(config.json_schema_name ?? "")}
              placeholder="workflow_output"
              onChange={setTextConfig("json_schema_name")}
            />
          </div>
          <div className={FIELD_BOX}>
            <span>{t("wfLlmJsonStrict")}</span>
            <Select
              value={String(config.json_schema_strict ?? "true")}
              onValueChange={(next) => setConfig("json_schema_strict", next)}
            >
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="true">{t("wfLlmJsonStrictOn")}</SelectItem>
                <SelectItem value="false">{t("wfLlmJsonStrictOff")}</SelectItem>
              </SelectContent>
            </Select>
          </div>
        </>
      )}
    </div>
  );
}
