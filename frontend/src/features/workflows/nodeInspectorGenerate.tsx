import React from "react";

import type { GenerationOption, WorkflowGraph } from "@/api/client";
import { useI18n } from "@/app/preferences";
import { RefCombobox } from "@/features/nodeForms/RefCombobox";
import { declaredChoices } from "@/components/generation/parameterPanel";
import { ModelFilePicker } from "@/components/generation/ModelFilePicker";
import { CustomSizePicker } from "@/components/generation/CustomSizePicker";
import { Input } from "@/components/ui/input";
import { OptionPicker } from "@/components/ui/option-picker";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { FIELD_BOX, type useNodeFieldOptions } from "@/features/nodeForms/NodeConfigForm";
import { RefEditor } from "@/features/nodeForms/RefEditor";
import { generationModelOf } from "@/features/workflows/readiness";
import {
  SOURCE_ROLE_LABELS,
  SOURCE_ROLE_ORDER,
  extraLines,
  parseSourceAssetText,
  readSourceAssets,
  sourceAssetText,
  writeSourceAssets,
  valueForRole,
  withRole,
} from "@/features/workflows/sourceAssetLines";
import type { SetGraphOptions } from "@/features/workflows/workflowGraphStore";
import {
  GENERATION_KINDS,
  type GenerationKind,
  durationOptions,
  durationRange,
  aspectRatioOptions,
  booleanParameterKeys,
  carriedParameters,
  declaredParameters,
  declaredParameterValue,
  withTriggerWords,
  durationChoices,
  type DeclaredParameter,
  sizeOptions,
  customSizeRule,
  countsRuns,
  maxImages,
  parameterChoiceEntries,
  runsHint,
  parseGenerationParameterInput,
  pickGenerationOption,
  promptMode,
  supportsParameter,
  sourceLabels,
  sourceLimit,
  videoResolutionOptions,
} from "@/lib/generationCapabilities";
import { formedGroups, generationPickerEntry } from "@/lib/entryNames";
import { GENERATION_KIND_LABELS, generationParameterLabel } from "@/lib/generationParameterLabels";

//: 节点检查器里「AI 生成素材」的专区:选模型、按模型能力铺参数、按角色挂输入素材。

/**
 * 属性面板里一格字段的样式(标签 + 控件 + 说明)。
 *
 * 这个常量早就有了,但注释里写着「面板里这串还散落在几十处内联」—— 那些内联已经在
 * 2026-08 的重做里全部收进来了(当时是十五处)。控件尺寸随之统一:输入框 h-8、
 * 内边距 px-2.5,不再有 p-1.5 和 h-9 两种说法。
 */
/** 生成节点里的一个参数控件:枚举给下拉、区间给数字框、布尔给开关。 */
interface GenField {
  key: string;
  label: string;
  options: string[];
  /** 可选值只是推荐、手填的也收(ComfyUI 工作流的尺寸):每边下限。 */
  custom?: { minimum: number };
  range?: { min: number; max: number };
  /** 控件下面那句说明(跑几遍那一格:一遍出几张、一共几张)。 */
  hint?: string;
  toggle?: boolean;
  /** 模型自己声明的参数(`parameter_schema`)。控件和取值都按它的声明来,见 DeclaredGenControl。 */
  declared?: DeclaredParameter;
}

/** 「AI 生成素材」自己渲染这几项,不走通用字段列表。
 *
 *  provider / model / kind 是**执行器要的形状**,不是用户要做的选择 —— 用户只决定一件事:
 *  用哪个生成模型。三者各自铺成必填框时,面板里会出现两个都叫「模型」的字段(一个选择器、
 *  一个输入框),外加一个能和模型矛盾的「类型」(选了图像模型却把类型填成 video)。
 *  parameters 同理:按模型能力生成的下拉已经在管它,再铺一个原始 JSON 框就是同一份东西两处编辑。 */
//: 生成节点里由专区自己渲染的配置项,不走通用字段列表。source_assets 在这里,是因为它在配置里
//: 是一段 `id:role` 的文本,而界面上该是**按角色一行一格** —— 让用户手写那段文本,角色名要背、
//: 冒号要记,写错了还不报错(后端拿不到角色就按默认走,于是"我明明挂了尾帧"的片子里没有尾帧)。
export const GENERATE_SPECIAL_CONFIG_KEYS = new Set([
  "provider_profile_id", "provider", "model", "kind", "parameters", "source_assets",
]);

/**
 * 模型自己声明的一个参数(插件生成供应商,见 lib/generationCapabilities.declaredParameters)。
 *
 * 可选值 / 开关给下拉,其余给输入框。第一项永远是「默认」= 不发,让模型用它自己的默认值 ——
 * 插件给的那个默认只拿来当提示,不替用户选(ADR 0015)。`typing` 告诉调用方这一下是不是打字
 * (撤销时要合并成一步,见 typingRun)。
 */
function DeclaredGenControl({
  parameter,
  value,
  onChange,
}: {
  parameter: DeclaredParameter;
  value: string;
  onChange: (text: string, typing: boolean) => void;
}) {
  const t = useI18n();
  const fallback = parameter.defaultValue === undefined ? "" : String(parameter.defaultValue);
  if (parameter.type === "boolean" || parameter.options.length > 0) {
    const choices = declaredChoices(parameter, t);
    return (
      <OptionPicker
        value={choices.shown(value)}
        onChange={(next) => onChange(choices.stored(next), false)}
        options={choices.options}
      />
    );
  }
  const numeric = parameter.type === "integer" || parameter.type === "number";
  return parameter.multiline ? (
    <textarea rows={4} value={value} placeholder={fallback} onChange={(event) => onChange(event.target.value, true)} />
  ) : (
    <Input
      type={numeric ? "number" : "text"}
      min={parameter.minimum}
      max={parameter.maximum}
      step={parameter.step ?? (numeric ? "any" : undefined)}
      value={value}
      placeholder={fallback || t("genDeclaredDefaultNone")}
      onChange={(event) => onChange(event.target.value, true)}
    />
  );
}

type NodeConfig = Record<string, unknown>;

/** 专区的状态:所选模型、它声明的参数、输入素材。NodeInspector 在原来那个位置调它。 */
export function useGenerateNodeSection({
  node,
  config,
  generationModels,
  onChange,
  setConfig,
  t,
}: {
  node: WorkflowGraph["nodes"][number];
  config: NodeConfig;
  generationModels: { options: GenerationOption[] };
  onChange: (patch: Partial<WorkflowGraph["nodes"][number]>, options?: SetGraphOptions) => void;
  setConfig: (key: string, value: unknown, options?: SetGraphOptions) => void;
  t: ReturnType<typeof useI18n>;
}) {
  /** 是否展开「手动指定 provider/model/类型」。目录里有的模型不需要看见这三项。 */
  const [genCustom, setGenCustom] = React.useState(false);
  const genModel = node.type === "ai_generate" ? generationModelOf(generationModels.options, config) : null;
  //: 还没选过模型的生成节点**预选这个人设的默认**(节点定了种类就只认那一种的默认)。没设默认就空着,
  //: 选择器说「选择要用的生成模型」—— 不拿清单第一项顶上(见 pickGenerationOption)。只填一次:之后
  //: 用户清掉、换掉都是他的事。
  const genDefault =
    node.type === "ai_generate" && !config.provider && !config.model
      ? config.kind
        ? pickGenerationOption(generationModels.options, { kind: String(config.kind) })
        : pickGenerationOption(generationModels.options, { kind: "image" }) ??
          pickGenerationOption(generationModels.options)
      : null;
  const preselectedFor = React.useRef<string | null>(null);
  React.useEffect(() => {
    if (!genDefault || preselectedFor.current === node.id) return;
    preselectedFor.current = node.id;
    onChange({
      config: {
        ...config,
        provider_profile_id: genDefault.provider_profile_id,
        provider: genDefault.provider,
        model: genDefault.model,
        kind: genDefault.kind,
      },
    });
  }, [genDefault, node.id, config, onChange]);
  //: 这个模型对提示词的要求:不收的把「提示词」一格藏起来,可以不写的说一句,要写的标必填
  //: (节点声明里不再标必填 —— 那是按模型变的,见后端 NODE_TYPES 的 ai_generate)。
  const genPromptMode = promptMode(genModel);
  const genParams = (config.parameters ?? {}) as Record<string, unknown>;
  const setGenParam = (key: string, value: string, options?: SetGraphOptions) => {
    const next = { ...genParams };
    // 空值就删掉这一项,而不是塞空串:后端会把空串当"显式指定了空"传给供应商。
    if (value === "") delete next[key];
    else next[key] = parseGenerationParameterInput(value);
    if (key === "resolution" && genModel && next.duration_seconds !== undefined) {
      const durations = durationChoices(genModel, value);
      if (durations.length > 0 && !durations.includes(Number(next.duration_seconds))) {
        next.duration_seconds = durations[0];
      }
    }
    setConfig("parameters", next, options);
  };
  /**
   * 该模型声明支持的参数。两种形状:
   *
   * - **枚举** —— 从若干可选值里挑一个(分辨率、宽高比);
   * - **区间** —— min..max 内的任意整数(时长)。Seedance 2 收 4–15 秒,写成枚举就只剩
   *   两个档,而用户看不出少了什么。
   */
  const genParamKeys: GenField[] = React.useMemo(() => {
    if (!genModel) return [];
    //: 每一格叫什么只问 generationParameterLabel —— 画布上引用写在这一格里时的输入口读的是同一个函数。
    const label = (key: string) => generationParameterLabel(key, genModel, t) || key;
    const out: GenField[] = [];
    const ratios = aspectRatioOptions(genModel);
    if (ratios.length > 0) out.push({ key: "aspect_ratio", label: label("aspect_ratio"), options: ratios });
    if (genModel.kind === "image") {
      const sizes = sizeOptions(genModel);
      if (sizes.length > 0) {
        out.push({ key: "size", label: label("size"), options: sizes, custom: customSizeRule(genModel) ?? undefined });
      }
      // 分辨率档(GPT Image 的 1K / 2K / 4K)决定像素预算、也就决定价钱:声明了才摆。
      const imageResolutions = videoResolutionOptions(genModel);
      if (imageResolutions.length > 0) out.push({ key: "resolution", label: label("resolution"), options: imageResolutions });
      // 一次出几张。此前工作流里没有这一栏 —— 而它是图像那边最常调的一个,
      // 生成面板有、节点没有,同一个模型两处能力不一样。
      const images = maxImages(genModel);
      if (supportsParameter(genModel, "num_images") && images > 1) {
        // ComfyUI 的工作流「张数」是跑几遍(countsRuns):名字由 generationParameterLabel 照实给,下面说清一遍出几张。
        const runs = Number(genParams.num_images) || 1;
        out.push({
          key: "num_images",
          label: label("num_images"),
          options: [],
          range: { min: 1, max: images },
          ...(countsRuns(genModel) ? { hint: runsHint(t, genModel, genParams, runs) } : {}),
        });
      }
    } else if (genModel.kind === "audio") {
      // 音频:时长是个可选的区间(多数音乐模型按歌词长短自己定曲长),歌词是一段长文字。
      const range = durationRange(genModel);
      const durations = durationOptions(genModel);
      if (supportsParameter(genModel, "duration_seconds")) {
        out.push(
          durations.length > 0
            ? { key: "duration_seconds", label: label("duration_seconds"), options: durations.map(String) }
            : { key: "duration_seconds", label: label("duration_seconds"), options: [], range: range ?? undefined },
        );
      }
      if (supportsParameter(genModel, "lyrics")) {
        out.push({
          key: "lyrics",
          label: label("lyrics"),
          options: [],
          declared: {
            key: "lyrics", type: "string", label: label("lyrics"), description: t("genLyricsHint"),
            defaultValue: undefined, options: [], optionLabels: {}, multiline: true, advanced: false,
          },
        });
      }
    } else {
      const resolutions = videoResolutionOptions(genModel);
      if (resolutions.length > 0) out.push({ key: "resolution", label: label("resolution"), options: resolutions });
      const durations = durationChoices(genModel, String(genParams.resolution ?? ""));
      if (durations.length > 0) {
        out.push({ key: "duration_seconds", label: label("duration_seconds"), options: durations.map(String) });
      }
    }
    // 开关类。**只在模型声明了的时候出现** —— 声明即接口,这里不按 kind 猜。
    for (const key of booleanParameterKeys(genModel)) {
      out.push({ key, label: label(key), options: [], toggle: true });
    }
    for (const [key, options] of parameterChoiceEntries(genModel)) {
      out.push({ key, label: label(key), options });
    }
    // 模型自己声明的参数(插件生成供应商:ComfyUI 每张工作流的采样器、步数……)。
    for (const parameter of declaredParameters(genModel)) {
      out.push({ key: parameter.key, label: label(parameter.key), options: [], declared: parameter });
    }
    return out;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [genModel, genParams.resolution]);

  /** 配置里那一列 `id:role`,解析成一条条素材。 */
  const genSourceLines = React.useMemo(
    () => readSourceAssets(config.source_assets),
    [config.source_assets],
  );
  /** 这个模型认哪几种素材角色 —— 描述符说了算,不按 kind 猜。 */
  const genSourceRoles = React.useMemo(
    () => (genModel ? SOURCE_ROLE_ORDER.filter((role) => supportsParameter(genModel, role)) : []),
    [genModel],
  );
  const genExtraSourceLines = React.useMemo(
    () => extraLines(genSourceLines, genSourceRoles as readonly string[]),
    [genSourceLines, genSourceRoles],
  );

  return {
    genCustom,
    setGenCustom,
    genModel,
    genPromptMode,
    genParams,
    setGenParam,
    genParamKeys,
    genSourceLines,
    genSourceRoles,
    genExtraSourceLines,
  };
}

/**
 * 专区的内容(参数档里、生成节点才有)。**是一个返回元素的函数,不是组件** —— 检查器直接调它,
 * React 树和拆出来之前一样。
 */
export function generateNodeSection({
  t,
  gen,
  config,
  generationModels,
  fieldOptions,
  variables,
  onChange,
  setConfig,
  setTextConfig,
  typeConfig,
  typingRun,
}: {
  t: ReturnType<typeof useI18n>;
  gen: ReturnType<typeof useGenerateNodeSection>;
  config: NodeConfig;
  generationModels: { options: GenerationOption[] };
  fieldOptions: ReturnType<typeof useNodeFieldOptions>;
  variables: string[];
  onChange: (patch: Partial<WorkflowGraph["nodes"][number]>, options?: SetGraphOptions) => void;
  setConfig: (key: string, value: unknown, options?: SetGraphOptions) => void;
  setTextConfig: (key: string) => (event: React.ChangeEvent<HTMLInputElement>) => void;
  typeConfig: (key: string) => (value: unknown) => void;
  typingRun: (field: string) => SetGraphOptions;
}): React.ReactElement {
  const {
    genCustom,
    setGenCustom,
    genModel,
    genParams,
    setGenParam,
    genParamKeys,
    genSourceLines,
    genSourceRoles,
    genExtraSourceLines,
  } = gen;
  const formed = formedGroups(generationModels.options);
  return (
    <div className="grid min-w-0 gap-2">
      <div className={FIELD_BOX}>
        <span>
          {t("wfGenModel")}
          <em className="font-bold not-italic text-destructive">*</em>
        </span>
        {/* 两层名字(ADR 0045):主名是这一项自己的(表单标题 / 工作流名),副名说来自哪张工作流、哪台服务器;按种类分组,
            同一张工作流的表单入口挂在完整工作流下面。和 AI Studio、画板同一种样子、同样的搜索。 */}
        <OptionPicker
          value={genModel?.id ?? ""}
          options={(generationModels.options).map((model) => {
            return {
              value: model.id,
              ...generationPickerEntry(model, formed, t),
              group: t(GENERATION_KIND_LABELS[model.kind as GenerationKind] ?? "capImage"),
            };
          })}
          placeholder={t("wfGenModelHint")}
          emptyText={t("cmdkEmpty")}
          ariaLabel={t("wfGenModel")}
          className="w-full"
          onChange={(id) => {
            const model = (generationModels.options).find((item) => item.id === id);
            if (!model) return;
            // 三者一起写:分开填就会出现「图像模型 + 类型 video」这种自相矛盾的组合。
            // 参数只留新模型仍收的:`{{…}}` 绑定照留(模板按开始参数接好的画幅、尺寸),写死的值新模型
            // 不收就丢 —— 上一个模型的比例 / 时长在新模型上未必存在(见 carriedParameters)。换了种类
            // (图像换成视频)就全清:那是另一种生成。
            onChange({
              config: {
                ...config,
                provider_profile_id: model.provider_profile_id,
                provider: model.provider,
                model: model.model,
                kind: model.kind,
                parameters: model.kind === config.kind ? carriedParameters(genParams, model) : {},
              },
            });
            setGenCustom(false);
          }}
        />
        {!genModel && !genCustom && (config.provider || config.model) ? (
          <small className="text-destructive">{t("wfGenModelUnknown")}</small>
        ) : (
          <small>{t("wfGenModelDesc")}</small>
        )}
        <button
          type="button"
          className="w-fit cursor-pointer border-0 bg-transparent p-0 text-ui-xs font-medium text-primary underline-offset-2 hover:underline"
          onClick={() => setGenCustom((prev) => !prev)}
        >
          {genCustom ? t("wfGenCustomHide") : t("wfGenCustomShow")}
        </button>
      </div>

      {/* 自定义端点上的模型目录里没有 —— 这时才需要看见执行器那三个字段。
          已配置但对不上目录时自动展开,否则用户会看到一个空选择器却不知道值存在哪。 */}
      {(genCustom || (!genModel && Boolean(config.provider || config.model))) && (
        <div className="grid min-w-0 gap-2 border-l-2 border-border pl-2">
          <div className={FIELD_BOX}>
            <span>{t("wffProvider")}</span>
            <Input
              value={String(config.provider ?? "")}
              placeholder="openai-compatible"
              onChange={setTextConfig("provider")}
            />
          </div>
          <div className={FIELD_BOX}>
            <span>{t("wffModel")}</span>
            <Input
              value={String(config.model ?? "")}
              onChange={setTextConfig("model")}
            />
          </div>
          <div className={FIELD_BOX}>
            <span>{t("wffKind")}</span>
            <Select value={String(config.kind ?? "image")} onValueChange={(next) => setConfig("kind", next)}>
              <SelectTrigger>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {GENERATION_KINDS.map((kind) => (
                  <SelectItem key={kind} value={kind}>{t(GENERATION_KIND_LABELS[kind])}</SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        </div>
      )}

      {/* 生成参数按所选模型的 capabilities 渲染 —— 目录声明支持什么就出现什么。 */}
      {genModel && genParamKeys.length > 0 && (
        <>
          {genParamKeys.map(({ key, label, options, range, hint, toggle, declared, custom }) => (
            <div className={FIELD_BOX} key={key}>
              <span>{label}</span>
              {/* 区间给数字框(上下界来自描述符),枚举给下拉。写死成下拉的话,
                  4–15 秒的模型只剩两个档,而用户看不出少了什么。 */}
              {declared && declared.modelFolder && genModel.plugin_instance_id && declared.options.length > 0 ? (
                /* 选模型文件的那一格:缩略图、底模、触发词来自这个连接的模型库;选中 LoRA 能把触发词加进提示词
                   (提示词是模板时照样接在末尾)。 */
                <ModelFilePicker
                  parameter={declared}
                  instanceId={genModel.plugin_instance_id}
                  value={genParams[key] === undefined ? "" : String(genParams[key])}
                  onChange={(text) => {
                    const next = { ...genParams };
                    const value = declaredParameterValue(declared, text);
                    if (value === undefined) delete next[key];
                    else next[key] = value;
                    setConfig("parameters", next);
                  }}
                  onUseTriggers={(words) => setConfig("prompt", withTriggerWords(String(config.prompt ?? ""), words))}
                />
              ) : declared ? (
                <DeclaredGenControl
                  parameter={declared}
                  value={genParams[key] === undefined ? "" : String(genParams[key])}
                  onChange={(text, typing) => {
                    const next = { ...genParams };
                    const value = declaredParameterValue(declared, text);
                    // 没动过 / 清空 = 不发,让模型用它自己的默认(见 ADR 0015)。
                    if (value === undefined) delete next[key];
                    else next[key] = value;
                    setConfig("parameters", next, typing ? typingRun(`parameters.${key}`) : undefined);
                  }}
                />
              ) : toggle ? (
                <Select
                  value={genParams[key] === undefined ? "" : String(Boolean(genParams[key]))}
                  onValueChange={(next) => setGenParam(key, next)}
                >
                  <SelectTrigger>
                    <SelectValue placeholder={t("wfGenToggleDefault")} />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="true">{t("wfGenToggleOn")}</SelectItem>
                    <SelectItem value="false">{t("wfGenToggleOff")}</SelectItem>
                  </SelectContent>
                </Select>
              ) : custom ? (
                <CustomSizePicker
                  value={String(genParams[key] ?? "")}
                  onChange={(next) => setGenParam(key, next)}
                  options={options}
                  minimum={custom.minimum}
                  ariaLabel={label}
                />
              ) : range ? (
                <Input
                  type="number"
                  min={range.min}
                  max={range.max}
                  value={String(genParams[key] ?? "")}
                  placeholder={`${range.min}–${range.max}`}
                  onChange={(event) => setGenParam(key, event.target.value, typingRun(`parameters.${key}`))}
                />
              ) : (
                <OptionPicker
                  value={String(genParams[key] ?? "")}
                  onChange={(next) => setGenParam(key, next)}
                  options={options.map((option) => ({
                    value: option,
                    label: key === "duration_seconds" && option === "-1" ? t("genDurationAuto") : option,
                  }))}
                  placeholder={t("wfPickOption")}
                />
              )}
              {hint ? <span className="text-ui-2xs leading-[1.45] text-muted-foreground">{hint}</span> : null}
            </div>
          ))}
          {supportsParameter(genModel, "seed") && (
            <div className={FIELD_BOX}>
              <span>{generationParameterLabel("seed", genModel, t)}</span>
              <Input
                type="number"
                value={String(genParams.seed ?? "")}
                placeholder={t("wfGenSeedHint")}
                onChange={(event) => setGenParam("seed", event.target.value, typingRun("parameters.seed"))}
              />
            </div>
          )}
        </>
      )}
      {/* 输入素材:**这个模型认哪几种角色就出哪几格**。每一格既能从素材库里选一份,
          也能填上游节点的输出(`{{ai-generate-1.asset_id}}`)—— 工作流里后者才是常态,
          所以用可手填的下拉,而不是纯选择器。 */}
      {genSourceRoles.map((role) => (
        <div className={FIELD_BOX} key={role}>
          <span>
            {t(SOURCE_ROLE_LABELS[role])}
            {sourceLimit(genModel, role) > 1 && (
              <small className="ml-auto font-normal opacity-60">
                {t("wfGenSourceMultiHint")}
              </small>
            )}
          </span>
          {/* 「值或上游输出」:工作流里这一格多半填的是上游输出(`{{ai-generate-1.asset_id}}`),
              上游的输出列在素材后面,引用显示成「节点 · 输出」的标签(见 RefCombobox)。 */}
          <RefCombobox
            value={valueForRole(genSourceLines, role)}
            options={fieldOptions.assets.map((asset) => ({
              value: asset.id,
              label: asset.name || asset.original_filename,
            }))}
            variables={variables}
            placeholder={t("wfGenSourcePlaceholder")}
            onValueChange={(next: string) =>
              setConfig("source_assets", writeSourceAssets(withRole(genSourceLines, role, next)))
            }
          />
          {/* 槽位按顺序叫什么(source_labels):一格里填几份时,第 i 份接到第 i 个名字的那个节点上 */}
          {sourceLabels(genModel, role).some(Boolean) && (
            <small data-source-labels={role}>
              {t("wfGenSourceSlotNames").replace(
                "{names}",
                sourceLabels(genModel, role).map((name, index) => name || `#${index + 1}`).join(t("listSeparator")),
              )}
            </small>
          )}
        </div>
      ))}
      {genExtraSourceLines.length > 0 && (
        // 换了模型之后不再被支持的角色。**不能悄悄丢掉** —— 用户换个模型看看效果,
        // 回来发现之前挂的东西没了,比多显示一行难受得多。
        <div className={FIELD_BOX}>
          <span>{t("wfGenSourceExtra")}</span>
          <RefEditor
            rows={Math.min(genExtraSourceLines.length + 1, 4)}
            value={sourceAssetText(genExtraSourceLines)}
            //: 存下去的是规整过的行(去空行、`x: role` → `x:role`),编辑器里留用户打的原样。
            normalize={(text) => sourceAssetText(parseSourceAssetText(text))}
            variables={variables}
            onChange={(next: string) =>
              typeConfig("source_assets")(
                writeSourceAssets([
                  ...genSourceLines.filter(
                    (line) => line.role && (genSourceRoles as readonly string[]).includes(line.role),
                  ),
                  ...parseSourceAssetText(next),
                ]),
              )
            }
          />
          <small>{t("wfGenSourceExtraHint")}</small>
        </div>
      )}
    </div>
  );
}
