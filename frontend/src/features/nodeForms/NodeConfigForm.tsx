import React from "react";
import { useQueries, useQuery } from "@tanstack/react-query";
import { Link2, PenLine } from "lucide-react";
import { toast } from "sonner";

import { fetchWorkflowFieldOptions, listAssets, type Asset } from "@/api/client";
import { useI18n } from "@/app/preferences";
import type { MessageKey } from "@/app/messages";
import { CodeEditor } from "@/components/app/code-editor";
import { AssetListField } from "@/features/nodeForms/AssetListField";
import { Combobox } from "@/components/app/combobox";
import { InlineMarkdown } from "@/components/markdown/InlineMarkdown";
import { toPlainText } from "@/components/markdown/inlineSyntax";
import { Input } from "@/components/ui/input";
import { OptionPicker } from "@/components/ui/option-picker";
import { NoteReferenceField } from "@/features/notes/NotePickerDialog";
import { fieldDataType } from "@/features/nodeForms/fieldTypes";
import { isWorkflowFieldActive } from "@/features/nodeForms/fieldActivation";
import { MapField, bareRef } from "@/features/nodeForms/MapField";
import { RefEditor } from "@/features/nodeForms/RefEditor";
import { ScenePropsField } from "@/features/nodeForms/ScenePropsField";
import { cn } from "@/lib/utils";

/**
 * **一份节点声明 → 一张表单。** 工作流的节点检查器用它;创意画板上「跑一个工具」的格子也要用它。
 *
 * 字段怎么渲染、下拉从哪来、哪些收进「高级」、哪些此刻不参与,全由后端的字段声明说了算
 * (`type` / `options_from` + `depends_on` / `allow_custom` / `editor` / `advanced` / `active_when`,
 * 见 backend/app/domain/workflows)。**这里不认识任何具体节点**(棘轮 nodeInspectorIsNodeAgnostic):
 * 插件节点是运行时才有的类型,按节点类型写的特例永远覆盖不到它。
 *
 * 宿主相关的两件事由调用方给:字段怎么「接上游」(`binding` —— 工作流里是数据边),以及它自己
 * 认得的特殊字段(`renderOwnField` —— 工作流的循环体概览)。
 */

export interface ConfigSpec {
  /** template(可插 `{{上游.输出}}` 的一段字)/ text(就是一段字,画板上的模板字段)/ string / number /
   *  object / code / asset_list … */
  type?: string;
  description?: string;
  required?: boolean;
  options?: string[];
  /** 清单之外还能不能手填(模型名那种:新模型上线往往早于目录更新)。 */
  allow_custom?: boolean;
  /** 选项的显示名(后端按语言翻好;值照旧是英文的,存进 config 的是它)。 */
  option_labels?: Record<string, string>;
  /** 后端声明的默认值,拿来做占位提示(告诉用户"留空会用什么")。 */
  default?: string;
  /** 留空也能跑的专业旋钮 —— 收进折叠的「高级选项」,不在第一眼糊到用户脸上。 */
  advanced?: boolean;
  /** 这个字段的值跟着谁走(后端 NODE_TYPES 声明)。父字段一换,这里的旧值就失效了。 */
  depends_on?: string;
  /** 选项要现查:来源名(后端 field_options)。清单跟着 depends_on 那个字段的值变。 */
  options_from?: string;
  /** 满足这些父字段取值时，本字段才参与表单、选项请求和校验。 */
  active_when?: Record<string, unknown | unknown[]>;
  /** 素材字段只收哪几种素材(image / video / audio;一种是字符串,几种是列表)—— 选择器只列那几种。 */
  media?: string | string[];
  /** 模板字段要写一段话(提示词):给高一点的编辑框。 */
  multiline?: boolean;
  /** 留空 = 清单里只有一项时就用它(运行时同一条规矩)。表单把那一项显示成当前值,不替人写进配置。 */
  sole_option_default?: boolean;
  /** 界面上叫什么(后端按语言翻好)。 */
  label?: string;
}

// Nested controls (such as MapField rows) own their dimensions and field styling.
export const FIELD_BOX =
  "grid gap-2 [&>span]:flex [&>span]:items-center [&>span]:gap-1 [&>span]:text-ui-sm [&>span]:font-medium [&>span]:text-foreground " +
  "[&_small]:text-ui-xs [&_small]:leading-[1.5] [&_small]:text-muted-foreground " +
  "[&>input]:h-10 [&>input]:w-full [&>input]:rounded-md [&>input]:border [&>input]:border-border [&>input]:bg-field [&>input]:px-2.5 [&>input]:text-ui-sm [&>input]:text-foreground " +
  "[&>textarea]:w-full [&>textarea]:resize-y [&>textarea]:rounded-md [&>textarea]:border [&>textarea]:border-border [&>textarea]:bg-field [&>textarea]:px-2.5 [&>textarea]:py-2 [&>textarea]:text-ui-sm [&>textarea]:text-foreground " +
  "[&>input:focus-visible]:border-primary [&>input:focus-visible]:outline-none " +
  "[&>textarea:focus-visible]:border-primary [&>textarea:focus-visible]:outline-none";

/**
 * 紧凑的一行一项(`compact`):标签在左、控件在右,标签小而淡,说明收进标签的悬停 —— 和生成面板
 * 「参数」弹层里那几行(ai-studio/parameterPanel 的 ParameterRow)同一个样子。画板上一格的能力的「参数」
 * 弹层用它:同一份字段渲染,不是工作流检查器那一列带大标签的表单。
 */
export const COMPACT_FIELD_BOX =
  "grid min-w-0 grid-cols-[112px_minmax(0,1fr)] items-center gap-x-3 gap-y-1 " +
  "[&>span]:flex [&>span]:min-w-0 [&>span]:items-center [&>span]:gap-1 [&>span]:text-ui-xs [&>span]:text-muted-foreground " +
  "[&>textarea]:w-full [&>textarea]:resize-y [&>textarea]:rounded-md [&>textarea]:border [&>textarea]:border-border [&>textarea]:bg-field [&>textarea]:px-2.5 [&>textarea]:py-1.5 [&>textarea]:text-ui-sm [&>textarea]:text-foreground " +
  "[&>textarea:focus-visible]:border-primary [&>textarea:focus-visible]:outline-none";

/** 一个现查的清单是空的时候,占位里怎么说(还在查 / 先填哪一格 / 那一格接的是上游 / 真的没有)。 */
export function emptyOptionsHint(t: (key: MessageKey) => string, why: EmptyOptions): string {
  if (why.kind === "pending") return t("wfOptionsLoading");
  if (why.kind === "parent") return t("wfPickParentFirst").replace("{field}", why.parent);
  if (why.kind === "upstream") return t("wfParentFromUpstream").replace("{field}", why.parent);
  return t("wfNoOptions");
}

/** object(JSON)字段:CodeMirror JSON 编辑,失焦解析回对象;非法给提示不写入。 */
export function JsonField({ value, onChange }: { value: unknown; onChange: (parsed: unknown) => void }) {
  const t = useI18n();
  const [text, setText] = React.useState(() => JSON.stringify(value ?? {}, null, 2));
  // 上游(智能体改图)更新时回显,但不打断正在输入:仅当序列化值真变才重置。
  const synced = React.useRef(text);
  React.useEffect(() => {
    const next = JSON.stringify(value ?? {}, null, 2);
    if (next !== synced.current) {
      synced.current = next;
      setText(next);
    }
  }, [value]);
  return (
    <CodeEditor
      value={text}
      language="json"
      minHeight={34}
      gutter={false}
      onChange={setText}
      onBlur={() => {
        try {
          const parsed = JSON.parse(text || "{}");
          synced.current = JSON.stringify(parsed ?? {}, null, 2);
          onChange(parsed);
        } catch {
          toast.error(t("wfBadJson"));
        }
      }}
    />
  );
}

/** code 字段保持纯编辑器；上游变量不再作为整片提示标签铺在表单下面。 */
function CodeField({ value, onChange }: { value: string; onChange: (value: string) => void }) {
  return <CodeEditor value={value} language="python" minHeight={140} onChange={onChange} />;
}

/** 这个节点**此刻**要渲染的字段,分「基础 / 高级」两档,顺序就是后端声明的顺序。

    不参与的字段(`active_when` 不满足)两档都不出现;`hidden` 是调用方自己的专区接管的字段。
    分级:留空也能跑的专业旋钮收进「高级」(由后端的 advanced 声明),第一眼只留下决定「这个节点
    在做什么」的字段 —— 十几个采样参数一上来就糊到脸上,新手根本无从下手。 */
export function nodeConfigTiers(
  specs: Record<string, ConfigSpec>,
  config: Record<string, unknown>,
  hidden: (key: string) => boolean = () => false,
): { basic: Array<[string, ConfigSpec]>; advanced: Array<[string, ConfigSpec]> } {
  const visible = Object.entries(specs)
    .filter(([, spec]) => isWorkflowFieldActive(spec, config, specs))
    .filter(([key]) => !hidden(key));
  return {
    basic: visible.filter(([, spec]) => !spec?.advanced),
    advanced: visible.filter(([, spec]) => Boolean(spec?.advanced)),
  };
}

/** 一个现查的清单**为什么是空的** —— 空下拉要说得出原因,而不是点开一片空白。 */
export type EmptyOptions =
  | { kind: "pending" }
  /** 它跟着的那个字段(`depends_on`)还没填。 */
  | { kind: "parent"; parent: string }
  /** 它跟着的那个字段接的是上游(或是一段 `{{…}}` 引用):清单要到运行时才知道。 */
  | { kind: "upstream"; parent: string }
  | { kind: "none" };

export interface NodeFieldOptions {
  /** 一个字段的下拉选项;返回 null 表示它不是下拉。 */
  dynamicOptions: (key: string, spec?: ConfigSpec) => Array<{ value: string; label: string }> | null;
  /** 现查的清单是空的时候,为什么。 */
  whyEmpty: (key: string) => EmptyOptions;
  /** 工作区素材(有素材字段时才拉)。 */
  assets: Asset[];
}

/** 值里有没有一段 `{{…}}` 引用。 */
export function hasReference(value: string): boolean {
  return /\{\{[^{}]+\}\}/.test(value);
}

/**
 * 字段的现查选项。每个声明了 `options_from` 的字段一份查询,父字段(`depends_on`)一换就重查;
 * 素材型字段给工作区素材。`nodeType` / `workflowId` 只是**转给后端**的上下文(插件节点的包名在
 * 类型里、可调用工作流要排掉自己),这里不据此分支。
 */
export function useNodeFieldOptions({
  specs,
  config,
  workspaceId,
  nodeType,
  workflowId = "",
  boundValues = {},
}: {
  specs: Record<string, ConfigSpec>;
  config: Record<string, unknown>;
  workspaceId: string;
  nodeType: string;
  workflowId?: string;
  /** 接了上游的字段 → 那个上游**此刻**给出的值(画板上场景格给场景 id);说不出(工作流里上游的
   *  输出要运行时才有)就是空串。依赖它的字段按这个值查清单 —— 值在绑定里,不在 config 里。 */
  boundValues?: Record<string, string>;
}): NodeFieldOptions {
  const optionSpecs = Object.entries(specs).filter(([, spec]) =>
    Boolean(spec?.options_from) && isWorkflowFieldActive(spec, config, specs),
  );
  /** 它跟着的那个字段现在是什么值;`upstream` = 值要到运行时才知道(接的上游、或是一段引用)。 */
  const parentOf = (spec?: ConfigSpec): { key: string; value: string; upstream: boolean } => {
    const key = spec?.depends_on ?? "";
    if (!key) return { key, value: "", upstream: false };
    if (key in boundValues) return { key, value: boundValues[key] ?? "", upstream: !boundValues[key] };
    const value = String(config[key] ?? specs[key]?.default ?? "");
    return { key, value, upstream: hasReference(value) };
  };
  const dynamicOptionResults = useQueries({
    queries: optionSpecs.map(([key, spec]) => {
      const parent = parentOf(spec);
      return {
        queryKey: ["workflow-field-options", spec?.options_from, workspaceId, parent.value, nodeType, workflowId, key],
        queryFn: () =>
          fetchWorkflowFieldOptions(String(spec?.options_from), workspaceId, parent.value, {
            nodeType,
            workflowId,
          }),
        // 父字段的值要到运行时才知道:问了也是空清单。
        enabled: !parent.upstream,
        staleTime: 30_000,
      };
    }),
  });
  const fetchedOptions = new Map(optionSpecs.map(([key], index) => [key, dynamicOptionResults[index]?.data ?? []]));
  const pendingOptions = new Set(
    optionSpecs.filter((_, index) => dynamicOptionResults[index]?.isLoading).map(([key]) => key),
  );
  // 强类型 asset 字段(如 素材转写.asset_id)手动模式下,给工作区素材下拉,免手填 UUID。
  const hasAssetField = Object.values(specs).some((spec) => fieldDataType(spec) === "asset");
  const assets = useQuery({
    queryKey: ["workflow-assets", workspaceId],
    queryFn: () => listAssets(workspaceId),
    enabled: hasAssetField,
  });

  /** 一个字段的下拉选项;返回 null 表示它不是下拉。

      **不认识任何具体节点。** 选项从哪来由声明说了算:`options_from` 的去问后端那一个接口
      (清单、依赖谁、怎么过滤都在后端 field_options),asset 型字段给工作区素材。此前这里按
      节点类型写着一串 if —— 插件的包和工具、发布账号、可调用工作流、对话连接与模型各一条,
      而插件节点是**运行时**才有的类型,前端那张表永远覆盖不到它。 */
  const dynamicOptions = (
    key: string,
    spec?: { options_from?: string },
  ): Array<{ value: string; label: string }> | null => {
    if (spec?.options_from) {
      return fetchedOptions.get(key) ?? [];
    }
    // asset 型字段:工作区素材下拉(label 用素材名,回退原始文件名)。按**数据类型**给,
    // 不按节点 —— 任何声明成 asset 的字段都该能挑素材。
    if (fieldDataType(spec as ConfigSpec | undefined) === "asset") {
      // 声明了素材种类的只列那几种:转 GIF 只收视频,转写只收音频和视频(一种是字符串,几种是列表)
      const declared = (spec as ConfigSpec | undefined)?.media;
      const media = declared === undefined ? [] : Array.isArray(declared) ? declared : [declared];
      return (assets.data ?? [])
        .filter((asset) => media.length === 0 || media.includes(asset.kind))
        .map((asset) => ({
          value: asset.id,
          label: asset.name || asset.original_filename,
        }));
    }
    return null;
  };

  const whyEmpty = (key: string): EmptyOptions => {
    const spec = specs[key];
    const parent = parentOf(spec);
    const parentName = parent.key ? String(specs[parent.key]?.label || parent.key) : "";
    if (parent.upstream) return { kind: "upstream", parent: parentName };
    if (pendingOptions.has(key) || (fieldDataType(spec) === "asset" && assets.isLoading)) return { kind: "pending" };
    if (parent.key && !parent.value) return { kind: "parent", parent: parentName };
    return { kind: "none" };
  };

  return { dynamicOptions, whyEmpty, assets: assets.data ?? [] };
}

/** 字段「接上游」的那一半,由宿主给。工作流里上游是图里别的节点的输出,连法是数据边;
 *  画板上是连进来的那几格(便签、文档、图片……),见 boards/ActionComposer。 */
export interface FieldBinding {
  /** 这个字段能不能接上游。不给 = 除对象字段外都能(工作流);画板上只有上游里有接得上的才能。 */
  canBind?: (key: string) => boolean;
  isBound: (key: string) => boolean;
  setBound: (key: string, bound: boolean) => void;
  /** 接上之后,这一格显示什么(挑哪个上游)。 */
  renderBound: (key: string) => React.ReactNode;
}

export function NodeConfigForm({
  fields,
  config,
  workspaceId,
  variables,
  fieldOptions,
  onSetConfig,
  onTypeConfig,
  binding,
  renderOwnField,
  references = false,
  compact = false,
}: {
  /** 要渲染的字段(nodeConfigTiers 的一档)。 */
  fields: Array<[string, ConfigSpec]>;
  config: Record<string, unknown>;
  workspaceId: string;
  /** 模板 / 映射字段里能插的变量(`{{上游.输出}}`)。 */
  variables: string[];
  fieldOptions: NodeFieldOptions;
  /** 离散的一步(换下拉、挑素材)。 */
  onSetConfig: (key: string, value: unknown) => void;
  /** 打字(一串连发):宿主可以把它在撤销历史里塌成一条。 */
  onTypeConfig: (key: string, value: unknown) => void;
  binding?: FieldBinding;
  /** 宿主自己认得的字段;返回 null 就按声明渲染。 */
  renderOwnField?: (key: string, spec: ConfigSpec) => React.ReactNode | null;
  /** 这个宿主里值能不能是一段 `{{上游.输出}}` 引用。工作流能(引擎对每个值都插值,循环体里的
   *  `{{loop.item.…}}` 也只能这么写);画板、插件的「试一下」不能 —— 那里的值就是字面量。
   *  能的话,挑东西的下拉在清单之外也收引用,并把上游的输出列在清单后面。 */
  references?: boolean;
  /** 一行一项的紧凑排法(见 COMPACT_FIELD_BOX):画板的「参数」弹层。缺省是检查器那一列。 */
  compact?: boolean;
}) {
  const t = useI18n();
  //: 紧凑排法里控件用 sm 档 —— 和生成面板「参数」弹层里的下拉同高。
  const size = compact ? "sm" : undefined;
  const setConfig = onSetConfig;
  const typeConfig = (key: string) => (value: unknown) => onTypeConfig(key, value);

  /** 哪些动态下拉允许手填值。

      素材/账号/音色这类**资源**是闭集:填一个不存在的 id 只会在运行时报错,所以下拉即全集。
      模型名不是:供应商上新模型往往早于我们的目录更新,只给下拉等于把人堵在「列表里没有、
      于是填不进去」的死角里。 */
  //: 清单之外还能不能手填,由**声明**说了算(后端 allow_custom)——此前是按字段名猜 key === "model"。
  const allowsCustomValue = (spec?: ConfigSpec) => Boolean(spec?.allow_custom);

  /** 引用也是一项:存的是 `{{source_video.asset_id}}`,列表里显示成不带花括号的 `source_video.asset_id`
   *  (和 MapField 同一个写法)。排在这个工作区的东西后面 —— 挑现成的是常态。 */
  const referenceOptions = references ? variables.map((ref) => ({ value: ref, label: bareRef(ref) })) : [];

  /** 现查的清单是空的:占位里说为什么(还在查 / 先填哪一格 / 那一格接的是上游 / 真的没有)。 */
  const emptyHint = (key: string): string => emptyOptionsHint(t, fieldOptions.whyEmpty(key));

  /** 一个配置字段的渲染。 */
  const renderField = ([key, spec]: [string, ConfigSpec]) => {
          // 调用方自己渲染的字段(工作流的循环体 / 子图概览):表单不认识它们是什么。
          const own = renderOwnField?.(key, spec);
          if (own) return <React.Fragment key={key}>{own}</React.Fragment>;
          const value = config[key];
          const isObject = spec?.type === "object";
          const isAssetList = spec?.type === "asset_list";
          const options = spec?.options
            ? spec.options.map((option) => ({ value: option, label: spec.option_labels?.[option] ?? option }))
            : fieldOptions.dynamicOptions(key, spec);
          // 标签由节点声明提供(后端内置节点和运行时插件走同一份接口),最后才退到裸键名。
          const declaredLabel = String((spec as { label?: unknown } | undefined)?.label ?? "").trim();
          // ComfyUI 式:非 object 字段都可切到"连接"(值从上游来,而不是手填)。上游是什么、怎么挑,
          // 由调用方的 binding 说 —— 工作流里是数据边。
          const canConnect = Boolean(binding) && !isObject && !isAssetList && (binding?.canBind?.(key) ?? true);
          const connected = canConnect && Boolean(binding?.isBound(key));
          return (
            <div className={compact ? COMPACT_FIELD_BOX : FIELD_BOX} key={key} data-field-key={key}>
              <span title={compact && spec?.description ? toPlainText(spec.description) : undefined}>
                {declaredLabel || key}
                {spec?.required ? <em className="font-bold not-italic text-destructive">*</em> : null}
                {canConnect && (
                  <button
                    type="button"
                    className={cn(
                      "ml-auto inline-flex cursor-pointer items-center gap-[3px] rounded-full border border-border bg-transparent px-1.5 py-px text-ui-2xs font-medium text-muted-foreground transition-[border-color,color,background] duration-100 hover:border-border-strong hover:text-foreground",
                      connected && "border-[color-mix(in_srgb,var(--primary)_45%,transparent)] bg-[color-mix(in_srgb,var(--primary)_10%,transparent)] text-primary hover:text-primary",
                    )}
                    title={t("wfInputModeHint")}
                    onClick={(event) => {
                      event.preventDefault();
                      binding?.setBound(key, !connected);
                    }}
                  >
                    {connected ? <Link2 size={11} /> : <PenLine size={11} />}
                    {connected ? t("wfInputRef") : t("wfInputManual")}
                  </button>
                )}
              </span>
              {connected ? (
                <div className="relative pl-3 before:absolute before:left-0 before:top-1/2 before:h-[7px] before:w-[7px] before:-translate-y-1/2 before:rounded-full before:bg-primary before:content-[''] [&_:where(button,[role=combobox])]:w-full">
                  {binding?.renderBound(key)}
                </div>
              ) : String((spec as { editor?: unknown } | undefined)?.editor ?? "") === "note_ref" ? (
                // 和下面的 scene_models 同一条:挑笔记这个控件由**后端的字段声明**点名。
                <NoteReferenceField workspaceId={workspaceId} value={String(value ?? "")} onChange={next => setConfig(key, next)} />
              ) : String((spec as { editor?: unknown } | undefined)?.editor ?? "") === "scene_models" ? (
                // 专用控件由**后端的字段声明**点名(editor: "scene_models"),不是这里按
                // 节点类型 + 字段名认出来的 —— 后者是这份注册表一直在消灭的那种手抄表。
                <ScenePropsField workspaceId={workspaceId} value={String(value ?? "")} onChange={next => setConfig(key, next)} />
              ) : isAssetList ? (
                // 一串素材:挑出来的一排标签 + 再加一份,不是一个写着 `[]` 的 JSON 框
                <AssetListField value={value} options={options ?? []} onChange={(next) => setConfig(key, next)} />
              ) : spec?.options && options ? (
                // 固定选项:闭集给纯下拉;声明了 allow_custom 的(逐镜决定的 source_group / render ——
                // 值常是上游的 `{{…}}`)走可手填的那一版,否则引用在纯下拉里显示成空白,也填不回去。
                !allowsCustomValue(spec) ? (
                  <OptionPicker
                    value={String(value ?? spec.default ?? "")}
                    onChange={(next) => setConfig(key, next)}
                    options={options}
                    placeholder={t("wfPickOption")}
                    size={size}
                  />
                ) : (
                  <Combobox
                    value={String(value ?? spec.default ?? "")}
                    options={options}
                    placeholder={t("wfPickOption")}
                    emptyText={t("cmdkEmpty")}
                    allowCustomValue
                    size={size}
                    className="w-full"
                    onValueChange={(next) => setConfig(key, next)}
                  />
                )
              ) : options ? (
                // 现查的清单(场景、镜头、项目、时间线、账号、音色、素材……):**挑一个**,不是抄一串 id。
                (() => {
                  const current = String(value ?? spec?.default ?? "");
                  //: 留空 = 唯一的那一项(sole_option_default):显示成当前值,不写进配置 —— 运行时同一条规矩。
                  const shown =
                    !current && spec?.sole_option_default && options.length === 1 ? options[0].value : current;
                  const placeholder = options.length > 0 ? t("wfPickOption") : emptyHint(key);
                  // 清单之外还收什么:声明了 allow_custom 的(模型名)什么都收;能写引用的宿主里收引用。
                  if (allowsCustomValue(spec) || references) {
                    const known = new Set(options.map((option) => option.value));
                    return (
                      <Combobox
                        value={shown}
                        options={[...options, ...referenceOptions.filter((option) => !known.has(option.value))]}
                        placeholder={placeholder}
                        emptyText={t("cmdkEmpty")}
                        allowCustomValue
                        acceptsCustomValue={allowsCustomValue(spec) ? undefined : hasReference}
                        customValueLabel={
                          allowsCustomValue(spec) ? undefined : (query) => t("wfUseReference").replace("{q}", query)
                        }
                        size={size}
                        className="w-full"
                        onValueChange={(next) => setConfig(key, next)}
                      />
                    );
                  }
                  // 画板、插件的「试一下」:值只能是清单里的一项 —— 标准下拉,项多了自动换成能搜的那一版。
                  return (
                    <OptionPicker
                      value={shown}
                      onChange={(next) => setConfig(key, next)}
                      options={options}
                      placeholder={placeholder}
                      disabled={options.length === 0}
                      size={size}
                    />
                  );
                })()
              ) : isObject ? (
                // 「名字 → 值」的映射给一行一对的编辑器,值那格能从上游输出里挑;
                // 真正自由结构的(json_schema)才留原始 JSON。哪种由声明说了算,见后端 config_editor。
                String((spec as { editor?: unknown } | undefined)?.editor ?? "") === "json" ? (
                  <JsonField value={value} onChange={(parsed) => setConfig(key, parsed)} />
                ) : (
                  <MapField
                    value={value}
                    variables={variables}
                    onChange={typeConfig(key)}
                  />
                )
              ) : spec?.type === "code" ? (
                <CodeField value={String(value ?? "")} onChange={typeConfig(key)} />
              ) : spec?.type === "text" ? (
                // 一段字,没有引用:创意画板上的模板字段就是这一种(后端 boards.transforms.board_config_view)——
                // 画板上没有「上游的输出」可引用,上游是连进来的格子,`{{…}}` 不该出现在创作者面前。
                <textarea
                  rows={spec?.multiline ? 4 : 2}
                  value={String(value ?? "")}
                  placeholder={spec?.default ? String(spec.default) : ""}
                  onChange={(event) => typeConfig(key)(event.target.value)}
                />
              ) : spec?.type === "template" ? (
                // 模板字段:多行,而且里面的 `{{上游.输出}}` 显示成**可整体删除的标签** ——
                // 纯文本时退格会把它咬成 `{{llm-1.tex`,而半截引用在运行前看不出错。
                <RefEditor
                  rows={spec?.multiline ? 4 : 2}
                  value={String(value ?? "")}
                  onChange={typeConfig(key)}
                  variables={variables}
                  placeholder={spec?.description ? undefined : t("wfRefEditorHint")}
                />
              ) : (
                // string / number 是单行值,以前也铺成可拖拽的多行文本域 —— 于是同一个面板里
                // 并排出现三种控件(Select / Combobox / 带拖拽手柄的文本域),看着像没做完。
                // 控件跟着字段声明的类型走。
                <Input
                  // 数字字段也是 text:引擎对每个字段都插值,`{{source_video.width}}` 在这里合法
                  // (官方模板就这么写)。type="number" 会把它当非法值显示成空,看着像没填,
                  // 顺手填个数就把引用覆盖了。inputMode 仍然给触控键盘弹数字键盘。
                  type="text"
                  size={size}
                  inputMode={spec?.type === "number" ? "decimal" : undefined}
                  value={String(value ?? "")}
                  placeholder={spec?.default ? String(spec.default) : ""}
                  onChange={(event) => typeConfig(key)(event.target.value)}
                />
              )}
              {spec?.description && !compact && (
                <small>
                  <InlineMarkdown text={spec.description} />
                </small>
              )}
            </div>
          );
  };

  return <>{fields.map(renderField)}</>;
}
