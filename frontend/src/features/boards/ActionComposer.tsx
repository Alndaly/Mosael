import React from "react";
import { useQuery } from "@tanstack/react-query";
import { Loader2, PlugZap } from "lucide-react";
import { toPlainText } from "@/components/markdown/inlineSyntax";

import { fetchWorkflowFieldOptions, type BoardItem, type BoardProducerInfo, type BoardRunForms } from "@/api/client";
import type { MessageKey } from "@/app/messages";
import { useI18n } from "@/app/preferences";
import { InlineMarkdown } from "@/components/markdown/InlineMarkdown";
import { OptionPicker } from "@/components/ui/option-picker";
import { BAR_PICKER, BoardComposerShell } from "@/features/boards/BoardComposerShell";
import { kindIcon, sourceName } from "@/features/boards/boardNodes";
import { defaultBindings, firstSentence, givesValue, sourceValue } from "@/features/boards/boardTools";
import { useSubmitting } from "@/features/boards/useSubmitting";
import {
  emptyOptionsHint,
  NodeConfigForm,
  nodeConfigTiers,
  useNodeFieldOptions,
  type ConfigSpec,
} from "@/features/nodeForms/NodeConfigForm";
import { dependentsCleared, withDependentsCleared } from "@/features/nodeForms/dependents";
import { fieldDataType } from "@/features/nodeForms/fieldTypes";
import { cn } from "@/lib/utils";

type Form = BoardRunForms["node"];

/** 「这个人的插件连接」那种选项的来源名(后端 field_options 的 plugin_instances)。 */
const CONNECTION_SOURCE = "plugin_instances";
type Bindings = Form["bindings"];

/** 工具清单里一个字段的声明:节点表单那一份 + 画板多给的一样 —— 它能接哪几种上游格子。 */
type BoardFieldSpec = ConfigSpec & { board_sources?: string[]; editor?: string };

/** 底栏里至多摆几枚设置芯片;其余的进「参数」。 */
const BAR_CHIP_LIMIT = 3;

/** 这个字段收一串还是一份:文字字段(多张便签按连线顺序拼起来)和复数的素材字段收一串。 */
function takesMany(key: string, spec: BoardFieldSpec): boolean {
  return Boolean(spec.board_sources?.includes("note")) || /(^|_)asset_ids$/.test(key);
}

/** 能接上游的格子(便签、文档、图片 …… 3D 场景)—— 后端说的(`board_sources`)。 */
function bindable(spec: BoardFieldSpec | undefined): boolean {
  return Boolean(spec?.board_sources?.length);
}

/** 挑一个的字段:声明了固定选项,或者选项要现查(`options_from`)。清单之外还能手填的(`allow_custom`)不算 ——
 *  芯片只能挑,那种字段进「参数」,在那里能手填。 */
function picksOne(spec: BoardFieldSpec | undefined): boolean {
  return Boolean((spec?.options?.length || spec?.options_from) && !spec?.allow_custom);
}

/** 一段自由的字(翻译的原文、出图的提示词):面板的正文就是它。挑一个的、素材、专用控件都不算。 */
function freeText(spec: BoardFieldSpec | undefined): boolean {
  return (
    (spec?.type === "text" || spec?.type === "template") &&
    !spec.options?.length &&
    !spec.options_from &&
    !spec.editor &&
    fieldDataType(spec) !== "asset"
  );
}

function filled(value: unknown): boolean {
  return typeof value === "number" || typeof value === "boolean" || (typeof value === "string" && value.trim() !== "");
}

/**
 * 工具格的面板:跑一个插件工具或工作流节点。**和画板上别的面板同一个壳**(BoardComposerShell),
 * 不是工作流检查器那一列带大标签的表单:
 *
 *  · **上面一排是上游芯片**。工作流里模板字段写 `{{上游.输出}}`;画板上没有「输出」可引用,上游是连进来的
 *    那几格 —— 能接上游的字段(后端说的 `board_sources`)各一组芯片,点哪一格就从哪一格取(便签给字、
 *    文档给正文、图片 / 视频 / 音频给素材、3D 场景给场景)。必填的默认接第一个接得上的上游,可以改,改了存在
 *    这一格上;值在运行时由服务端从画布上取。
 *  · **正文是那段自由的字**(第一个没接上游的文字字段:翻译的原文、出图的提示词)。没有这样的字段时,正文是
 *    工具那一句说明。
 *  · **底栏是设置芯片**:挑一个的字段(固定选项、现查的清单),必填的在前,至多三枚 —— 「目标语言 英语 ▾」
 *    「场景 客厅 ▾」「镜头 ▾」。**其余的进「参数」**,和生成面板的模型参数同一个弹层;里面有必填还空着时,
 *    按钮上一个点。发送键是同一枚圆键。
 *
 * **表单不是为这一个工具写的。** 分到哪一块全按字段声明(`board_sources` / `options` / `options_from` /
 * `allow_custom` / `required` / `advanced` / `active_when`)推;「参数」里的字段用的是节点表单那一份渲染
 * (NodeConfigForm 的紧凑排法),下拉的来源、跟着谁变、唯一一项当缺省也都是它那一份(useNodeFieldOptions)——
 * 这里不认识任何具体节点(棘轮 nodeInspectorIsNodeAgnostic)。
 *
 * **用谁的连接**:插件工具跑的是点运行的这个人自己接的连接 —— 共享画板上尤其如此。有连接时不说(一行
 * 「将用你的连接 X 运行」是噪音,用户说过不要);**没有**时说清楚、给一个去插件页的入口,发送键是灰的。
 *
 * **还差什么没填,发送键就是灰的**,悬停说差哪几样 —— 此前必填的场景空着,发送键照样亮着,点了才从服务端
 * 回一句错。
 */
export function ActionComposer({
  item,
  tool,
  sources,
  workspaceId,
  busy,
  onFormChange,
  onRun,
}: {
  /** 面板看到的那一格(表单里不带产出者,见 boardItemState.composerView)。 */
  item: BoardItem;
  /** 这一格跑的工具。null = 这个人此刻用不了它;undefined = 清单还在路上。 */
  tool: BoardProducerInfo | null | undefined;
  /** 连进来的上游,按连线的先后。 */
  sources: BoardItem[];
  workspaceId: string;
  busy: boolean;
  onFormChange: (form: NonNullable<BoardItem["form"]>) => void;
  onRun: (form: Form) => Promise<unknown>;
}) {
  const t = useI18n();
  const specs = React.useMemo(() => (tool?.config ?? {}) as Record<string, BoardFieldSpec>, [tool]);
  const config = React.useMemo(() => item.form?.config ?? {}, [item.form?.config]);
  const bindings = React.useMemo(() => item.form?.bindings ?? {}, [item.form?.bindings]);
  const nodeType = tool?.type ?? "";
  //: 接了上游的字段此刻的值(第一格给得出值的上游,按连线先后)。「镜头」跟着「3D 场景」:场景接的是
  //: 画布上的场景格时,镜头清单按那一格的场景查 —— 值在绑定里,不在 config 里。
  const boundValues = React.useMemo(() => {
    const out: Record<string, string> = {};
    for (const [key, refs] of Object.entries(bindings)) {
      if (!refs?.length) continue;
      const wanted = new Set(refs.map((one) => one.from));
      const first = sources.find((one) => wanted.has(one.id) && givesValue(one));
      out[key] = first ? sourceValue(first) : "";
    }
    return out;
  }, [bindings, sources]);
  const fieldOptions = useNodeFieldOptions({ specs, config, workspaceId, nodeType, boundValues });
  const { submitting, run } = useSubmitting();
  const working = submitting || busy;

  const save = React.useCallback(
    (next: { config?: Record<string, unknown>; bindings?: Bindings }) =>
      onFormChange({ ...item.form, config: next.config ?? config, bindings: next.bindings ?? bindings }),
    [onFormChange, item.form, config, bindings],
  );

  //: 必填字段默认接第一个接得上的上游 —— 连了线还要再点一下「从上游取」,那条线就白连了。
  React.useEffect(() => {
    const next = defaultBindings(specs, config, bindings, sources);
    if (next) save({ bindings: next });
  }, [specs, config, bindings, sources, save]);

  //: 插件工具用谁的连接:认的是**声明**(选项来自「这个人的插件连接」的那个字段),不是字段名。
  //: 和表单里那个下拉同一份查询(同一个缓存键),多一个「还在查」。
  const connectionKey = Object.keys(specs).find((key) => specs[key]?.options_from === CONNECTION_SOURCE) ?? "";
  const connectionSpec = connectionKey ? specs[connectionKey] : undefined;
  const connections = useQuery({
    queryKey: ["workflow-field-options", connectionSpec?.options_from, workspaceId, "", nodeType, "", connectionKey],
    queryFn: () =>
      fetchWorkflowFieldOptions(String(connectionSpec?.options_from), workspaceId, "", { nodeType, workflowId: "" }),
    enabled: Boolean(connectionSpec?.options_from),
    staleTime: 30_000,
  });
  const plugin = tool?.plugin_name ?? "";
  const available = connections.data ?? [];
  const missingConnection = Boolean(connectionSpec?.options_from) && connections.isSuccess && available.length === 0;

  const fits = (key: string) =>
    sources.filter((one) => specs[key]?.board_sources?.includes(one.kind) && givesValue(one));
  const isBound = (key: string) => Boolean(bindings[key]?.length);
  //: 换了接哪一格,这个字段的值就换了 —— 跟着它的字段(镜头跟着场景)一并清掉,和手填换值同一条。
  const unbind = (key: string) => {
    const { [key]: _dropped, ...rest } = bindings;
    //: 切回手填:把这个键写进 config(空串也算),默认绑定就不会刚解开又绑回去。
    save({ bindings: rest, config: dependentsCleared(key in config ? config : { ...config, [key]: "" }, key, specs) });
  };
  const toggleSource = (key: string, source: BoardItem) => {
    const current = bindings[key] ?? [];
    const on = current.some((one) => one.from === source.id);
    const next = on
      ? current.filter((one) => one.from !== source.id)
      : takesMany(key, specs[key] ?? {})
        ? [...current, { from: source.id }]
        : [{ from: source.id }];
    if (next.length === 0) unbind(key);
    else save({ bindings: { ...bindings, [key]: next }, config: dependentsCleared(config, key, specs) });
  };
  //: 换了父字段就清掉跟着它的(换场景 → 旧镜头失效),和工作流检查器同一条规矩(nodeForms/dependents)。
  const setConfig = (key: string, value: unknown) => save({ config: withDependentsCleared(config, key, value, specs) });

  const fieldLabel = (key: string, spec: BoardFieldSpec) => String(spec.label || key);

  //: 分到哪一块:上游芯片(能接上游、有得接或已经接上)、正文(第一段自由的字)、底栏芯片(挑一个的,必填在前)、
  //: 其余进「参数」。只看此刻参与的字段(active_when)。
  const { basic, advanced } = nodeConfigTiers(specs, config);
  const active = [...basic, ...advanced];
  const upstreamFields = active.filter(([key, spec]) => bindable(spec) && (fits(key).length > 0 || isBound(key)));
  const bodyField = basic.find(([key, spec]) => freeText(spec) && !isBound(key));
  const chipFields = basic
    .filter(([key, spec]) => picksOne(spec) && !isBound(key) && key !== bodyField?.[0])
    .sort(([, a], [, b]) => Number(Boolean(b.required)) - Number(Boolean(a.required)))
    .slice(0, BAR_CHIP_LIMIT);
  const placed = new Set([bodyField?.[0], ...chipFields.map(([key]) => key)]);
  const rest = (fields: Array<[string, BoardFieldSpec]>) => fields.filter(([key]) => !placed.has(key) && !isBound(key));
  const restBasic = rest(basic);
  const restAdvanced = rest(advanced);
  //: 「参数」里有必填还空着的:按钮上一个点 —— 不点开就看不见的必填,不能让它安静地缺着。
  const attention = [...restBasic, ...restAdvanced].some(
    ([key, spec]) => spec.required && !filled(config[key]) && !filled(spec.default),
  );

  //: 还差哪几样必填:没接上游、没填、没有缺省,也不是「清单只有一项就用它」的那种。
  const soleDefault = (key: string, spec: BoardFieldSpec) =>
    Boolean(spec.sole_option_default) && (fieldOptions.dynamicOptions(key, spec) ?? []).length === 1;
  const missing = active
    .filter(([key, spec]) => spec.required && !isBound(key) && !filled(config[key]) && !filled(spec.default) && !soleDefault(key, spec))
    .map(([key, spec]) => fieldLabel(key, spec));
  const blocked = !tool || missingConnection || missing.length > 0;
  const send = () => {
    if (blocked || working) return;
    run(() => onRun({ config, bindings }));
  };

  return (
    <BoardComposerShell
      nodeId={item.id}
      name="tool"
      upstream={
        tool && upstreamFields.length > 0
          ? upstreamFields.map(([key, spec]) => {
              const picked = new Set((bindings[key] ?? []).map((one) => one.from));
              return (
                <span
                  key={key}
                  role="group"
                  aria-label={fieldLabel(key, spec)}
                  data-binding-chips={key}
                  className="flex min-w-0 flex-wrap items-center gap-1"
                >
                  <span className="px-1 text-ui-xs text-muted-foreground">{fieldLabel(key, spec)}</span>
                  {fits(key).map((source) => {
                    const Icon = kindIcon(source.kind);
                    const on = picked.has(source.id);
                    return (
                      <button
                        key={source.id}
                        type="button"
                        aria-pressed={on}
                        data-binding-source={source.id}
                        title={sourceName(t, source)}
                        onClick={() => toggleSource(key, source)}
                        className={cn(
                          "inline-flex h-6 max-w-full cursor-pointer items-center gap-1 rounded-full border px-2 text-ui-2xs transition-colors",
                          on
                            ? "border-[color-mix(in_srgb,var(--primary)_45%,transparent)] bg-[color-mix(in_srgb,var(--primary)_10%,transparent)] text-primary"
                            : "border-border text-muted-foreground hover:border-border-strong hover:text-foreground",
                        )}
                      >
                        <Icon size={11} className="shrink-0" />
                        <span className="truncate">{sourceName(t, source)}</span>
                      </button>
                    );
                  })}
                </span>
              );
            })
          : null
      }
      bar={
        tool
          ? chipFields.map(([key, spec]) => {
              const options = spec.options?.length
                ? spec.options.map((option) => ({ value: option, label: spec.option_labels?.[option] ?? option }))
                : (fieldOptions.dynamicOptions(key, spec) ?? []);
              const current = String(config[key] ?? spec.default ?? "");
              //: 留空 = 唯一的那一项(sole_option_default):显示成当前值,不写进配置 —— 运行时同一条规矩。
              const shown = !current && spec.sole_option_default && options.length === 1 ? options[0].value : current;
              //: **芯片上写的是值**(「英语」「客厅」),和模型芯片写模型名一样;还没选时写字段名(「目标语言」),
              //: 淡色。字段名不和值挤在同一枚芯片里 —— 此前「目标语言 待选」在窄处被截成「镜头 先…」,两样都看不清。
              //: 清单是空的(先选场景 / 还在查 / 真没有)芯片是灰的,原因在悬停里说。
              const emptyWhy = options.length === 0 ? emptyOptionsHint(t, fieldOptions.whyEmpty(key)) : "";
              return (
                <span
                  key={key}
                  data-field-key={key}
                  //: 宽度上限挂在**这一层**(相对整条底栏的 45%),芯片自己撑满这一层 —— 上限写在芯片上的话,百分比
                  //: 相对的是这层按内容定宽的包装,一来一回把字的宽度压成了 0(「镜头 先…」就是这么被截掉的)。
                  className="flex min-w-0 max-w-[min(15rem,45%)] shrink"
                  title={emptyWhy ? `${fieldLabel(key, spec)} · ${emptyWhy}` : fieldLabel(key, spec)}
                >
                  <OptionPicker
                    size="sm"
                    ariaLabel={fieldLabel(key, spec)}
                    value={shown}
                    onChange={(next) => setConfig(key, next)}
                    options={options}
                    disabled={options.length === 0}
                    placeholder={fieldLabel(key, spec)}
                    className={cn(BAR_PICKER, "max-w-full", shown && "text-foreground")}
                    contentClassName="max-w-[min(360px,calc(100vw-16px))]"
                  />
                </span>
              );
            })
          : null
      }
      settings={
        tool && (restBasic.length > 0 || restAdvanced.length > 0)
          ? {
              attention,
              //: **一张表,一种排法**:常用的在前、不常用的在后,一行一项、标签在左。此前中间插一行「高级选项」
              //: 把它切成两段,两段各自排版,看着像两张表。
              content: (
                <NodeConfigForm
                  compact
                  fields={[...restBasic, ...restAdvanced]}
                  config={config}
                  workspaceId={workspaceId}
                  variables={[]}
                  fieldOptions={fieldOptions}
                  onSetConfig={setConfig}
                  onTypeConfig={setConfig}
                />
              ),
            }
          : null
      }
      send={
        tool
          ? {
              label: t(item.run?.status === "succeeded" ? "boardToolRerun" : "boardToolRun"),
              hint: missing.length > 0 ? t("boardToolMissing").replace("{fields}", missing.join(t("listSeparator"))) : t("boardToolOutputsHint"),
              onSend: send,
              disabled: blocked,
              working,
            }
          : null
      }
    >
      {tool === undefined ? (
        <div role="status" className="flex items-center gap-2 px-1 py-2 text-ui-xs text-muted-foreground">
          <Loader2 size={13} className="animate-spin" /> {t("boardKindAction")}
        </div>
      ) : tool === null ? (
        <p role="alert" className="m-0 px-1 py-2 text-ui-xs leading-relaxed text-muted-foreground">
          {t("boardToolUnavailable")}{" "}
          <a href="#/plugins" className="text-primary underline-offset-2 hover:underline">
            {t("boardToolOpenPlugins")}
          </a>
        </p>
      ) : (
        <>
          {bodyField ? (
            <textarea
              data-field-key={bodyField[0]}
              aria-label={fieldLabel(...bodyField)}
              value={String(config[bodyField[0]] ?? "")}
              onChange={(event) => setConfig(bodyField[0], event.target.value)}
              rows={bodyField[1].multiline ? 4 : 3}
              placeholder={bodyPlaceholder(t, ...bodyField)}
              className="nowheel w-full resize-none border-0 bg-transparent px-1 py-1 text-ui-sm leading-relaxed text-foreground outline-none placeholder:text-muted-foreground"
            />
          ) : tool.board_description ? (
            //: 没有要写的字:正文是这个工具那一句说明(给创作者看的「它把内容变成什么」)。
            <p className="m-0 px-1 py-1 text-ui-sm leading-relaxed text-muted-foreground">
              <InlineMarkdown text={tool.board_description} />
            </p>
          ) : null}
          {missingConnection ? (
            <p data-tool-connection="" className="m-0 flex items-start gap-1.5 px-1 text-ui-xs leading-relaxed text-muted-foreground">
              <PlugZap size={13} className="mt-0.5 shrink-0" />
              <span role="alert" className="text-foreground">
                {t("boardToolNoConnection").replace("{plugin}", plugin)}{" "}
                <a href="#/plugins" className="text-primary underline-offset-2 hover:underline">
                  {t("boardToolOpenPlugins")}
                </a>
              </span>
            </p>
          ) : null}
        </>
      )}
    </BoardComposerShell>
  );
}

/** 正文的占位:这一格要写什么(字段自己的说明,第一句),没有说明时是「写下{字段}」—— 不是光秃秃的字段名
 *  (「文本」「Key」读起来像一个没填的表单标签)。 */
function bodyPlaceholder(t: (key: MessageKey) => string, key: string, spec: BoardFieldSpec): string {
  const said = spec.description ? firstSentence(toPlainText(String(spec.description))) : "";
  return said || t("boardToolBodyPlaceholder").replace("{field}", String(spec.label || key));
}
