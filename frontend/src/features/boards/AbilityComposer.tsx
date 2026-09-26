import React from "react";
import { useQuery } from "@tanstack/react-query";
import { Loader2, PlugZap } from "lucide-react";
import { toPlainText } from "@/components/markdown/inlineSyntax";

import {
  fetchWorkflowFieldOptions,
  type BoardAbilitySetting,
  type BoardItem,
  type BoardProducerInfo,
  type BoardRunForms,
} from "@/api/client";
import type { MessageKey } from "@/app/messages";
import { useI18n } from "@/app/preferences";
import { AssetInlinePreview } from "@/components/app/asset-preview";
import { InlineMarkdown } from "@/components/markdown/InlineMarkdown";
import { OptionPicker } from "@/components/ui/option-picker";
import { BAR_PICKER, BoardComposerShell } from "@/features/boards/BoardComposerShell";
import { kindIcon, sourceName } from "@/features/boards/boardNodes";
import { boardToolIcon, defaultBindings, firstSentence, givesValue, sourceValue } from "@/features/boards/boardTools";
import { composerFields, filled, missingFields, takesMany, type BoardFieldSpec } from "@/features/boards/composerFields";
import { useSubmitting } from "@/features/boards/useSubmitting";
import { emptyOptionsHint, NodeConfigForm, useNodeFieldOptions } from "@/features/nodeForms/NodeConfigForm";
import { dependentsCleared, withDependentsCleared } from "@/features/nodeForms/dependents";
import { cn } from "@/lib/utils";

type Form = BoardRunForms["node"];
type Bindings = Form["bindings"];

/** 「这个人的插件连接」那种选项的来源名(后端 field_options 的 plugin_instances)。 */
const CONNECTION_SOURCE = "plugin_instances";

/**
 * 一格的**能力**(音频格上的转写、便签上的翻译、ComfyUI 的一张处理图片的工作流……)的面板,也是空格子上
 * **生成器**(按参数出图出片的插件工具)的面板。**和画板上别的面板同一个壳**(BoardComposerShell):
 *
 *  · **正文先说这一下对这一格做什么**:宿主那一格(一张小图 / 种类图标 + 它的名字)和一句「把音频或视频里说的话
 *    转成文字」(工具给创作者看的那一句,`board_description`)。宿主的内容**就是**工具的那个输入(后端
 *    `host_fields`),不是一枚芯片、不是一个要填的字段。生成器没有宿主,正文是那段自由的字(提示词),没有就是
 *    那一句说明。
 *  · **上面一排是上游芯片**:工具别的输入(多输入的工具)接连进这一格的上游,点哪一格就从哪一格取;必填的
 *    默认接第一个接得上的,值在运行时由服务端从画布上取。
 *  · **底栏是设置芯片**:挑一个的字段,必填的在前,至多三枚 —— 芯片上写的是**值**(「英语」),还没选时写
 *    字段名。其余进「参数」;里面有必填还空着时,按钮上一个点。
 *  · **圆形发送键**:还差必填的就是灰的,悬停说差哪几样;没有这个插件的连接时也是灰的,正文里说清楚、给去插件页
 *    的入口(有连接时不说 —— 「将用你的连接 X」是噪音)。
 *
 * 分到哪一块全按字段声明推(composerFields),这里不认识任何具体节点(棘轮 nodeInspectorIsNodeAgnostic)。
 */
export function AbilityComposer({
  item,
  tool,
  hostField,
  setting,
  sources,
  workspaceId,
  busy,
  onFormChange,
  onRun,
}: {
  /** 挂着它的那一格(一项能力的宿主,或生成器填的那个空格子)。 */
  item: BoardItem;
  /** 这一项的声明(后端 GET /api/boards/producers)。null = 这个人此刻用不了它;undefined = 清单还在路上。 */
  tool: BoardProducerInfo | null | undefined;
  /** 宿主的内容填进哪个字段(一项能力);生成器没有 —— 它不吃画板上的内容。 */
  hostField?: string | null;
  /** 这一项此刻的设置(能力:`form.abilities[id]`;生成器:这一格自己的 `config` / `bindings`)。 */
  setting: BoardAbilitySetting;
  /** 连进这一格的上游,按连线的先后。 */
  sources: BoardItem[];
  workspaceId: string;
  busy: boolean;
  onFormChange: (setting: Form) => void;
  onRun: (form: Form) => Promise<unknown>;
}) {
  const t = useI18n();
  const ability = hostField !== undefined;
  const specs = React.useMemo(() => (tool?.config ?? {}) as Record<string, BoardFieldSpec>, [tool]);
  const config = React.useMemo(() => setting.config ?? {}, [setting.config]);
  const bindings = React.useMemo(() => setting.bindings ?? {}, [setting.bindings]);
  const nodeType = tool?.type ?? "";
  //: 接了上游的字段此刻的值(第一格给得出值的上游,按连线先后);宿主那个字段的值就是宿主给的 ——
  //: 跟着它的字段(镜头跟着场景)按它查清单。
  const boundValues = React.useMemo(() => {
    const out: Record<string, string> = {};
    for (const [key, refs] of Object.entries(bindings)) {
      if (!refs?.length) continue;
      const wanted = new Set(refs.map((one) => one.from));
      const first = sources.find((one) => wanted.has(one.id) && givesValue(one));
      out[key] = first ? sourceValue(first) : "";
    }
    if (hostField) out[hostField] = sourceValue(item);
    return out;
  }, [bindings, sources, hostField, item]);
  const fieldOptions = useNodeFieldOptions({ specs, config, workspaceId, nodeType, boundValues });
  const { submitting, run } = useSubmitting();
  const working = submitting || busy;

  const save = React.useCallback(
    (next: { config?: Record<string, unknown>; bindings?: Bindings }) =>
      onFormChange({ config: next.config ?? config, bindings: next.bindings ?? bindings }),
    [onFormChange, config, bindings],
  );

  //: 宿主字段不参与默认绑定、不列芯片:它就是宿主。
  const otherSpecs = React.useMemo(
    () => (hostField ? Object.fromEntries(Object.entries(specs).filter(([key]) => key !== hostField)) : specs),
    [specs, hostField],
  );
  //: 必填字段默认接第一个接得上的上游 —— 连了线还要再点一下「从上游取」,那条线就白连了。
  React.useEffect(() => {
    const next = defaultBindings(otherSpecs, config, bindings, sources.filter((one) => one.id !== item.id));
    if (next) save({ bindings: next });
  }, [otherSpecs, config, bindings, sources, save, item.id]);

  //: 插件工具用谁的连接:认的是**声明**(选项来自「这个人的插件连接」的那个字段),不是字段名。
  const connectionKey = Object.keys(specs).find((key) => specs[key]?.options_from === CONNECTION_SOURCE) ?? "";
  const connectionSpec = connectionKey ? specs[connectionKey] : undefined;
  const connections = useQuery({
    queryKey: ["workflow-field-options", connectionSpec?.options_from, workspaceId, "", nodeType, "", connectionKey],
    queryFn: () =>
      fetchWorkflowFieldOptions(String(connectionSpec?.options_from), workspaceId, "", { nodeType, workflowId: "" }),
    enabled: Boolean(connectionSpec?.options_from),
    staleTime: 30_000,
  });
  const missingConnection = Boolean(connectionSpec?.options_from) && connections.isSuccess && (connections.data ?? []).length === 0;

  const fits = (key: string) =>
    sources.filter((one) => one.id !== item.id && specs[key]?.board_sources?.includes(one.kind) && givesValue(one));
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
  //: **只有一个连接时不摆「连接」**:留空就是用它(sole_option_default,运行时同一条),摆出来只会在「从网盘导入」
  //: 下面再写一遍「百度网盘」。有两个以上才是一个要挑的东西;值已经写成别的(那个连接删了)时也摆出来让人看见。
  const soleConnection =
    Boolean(connectionKey) &&
    connections.isSuccess &&
    (connections.data ?? []).length === 1 &&
    (!filled(config[connectionKey]) || config[connectionKey] === connections.data?.[0]?.value);
  const fields = composerFields({ specs, config, bindings, hostField, fits, hidden: soleConnection ? connectionKey : null });
  const soleDefault = (key: string, spec: BoardFieldSpec) =>
    Boolean(spec.sole_option_default) && (fieldOptions.dynamicOptions(key, spec) ?? []).length === 1;
  const missing = missingFields(fields, config, bindings, soleDefault).map(([key, spec]) => fieldLabel(key, spec));
  const blocked = !tool || missingConnection || missing.length > 0;
  const send = () => {
    if (blocked || working) return;
    run(() => onRun({ config, bindings }));
  };
  //: 这一格上一轮跑的就是这一项、而且没跑成:原因写在面板里(格子上只在选中时挂一条)。
  const failed =
    item.run?.status === "failed" && (ability ? item.run.ability === tool?.id : !item.run.ability) ? item.run.error : undefined;

  return (
    <BoardComposerShell
      nodeId={item.id}
      name={ability ? "ability" : "generator"}
      upstream={
        tool && fields.upstream.length > 0
          ? fields.upstream.map(([key, spec]) => {
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
          ? fields.chips.map(([key, spec]) => {
              const options = spec.options?.length
                ? spec.options.map((option) => ({ value: option, label: spec.option_labels?.[option] ?? option }))
                : (fieldOptions.dynamicOptions(key, spec) ?? []);
              const current = String(config[key] ?? spec.default ?? "");
              //: 留空 = 唯一的那一项(sole_option_default):显示成当前值,不写进配置 —— 运行时同一条规矩。
              const shown = !current && spec.sole_option_default && options.length === 1 ? options[0].value : current;
              //: **芯片上写的是值**(「英语」「客厅」),还没选时写字段名(「目标语言」),淡色。清单是空的
              //: (先选场景 / 还在查 / 真没有)芯片是灰的,原因在悬停里说。
              const emptyWhy = options.length === 0 ? emptyOptionsHint(t, fieldOptions.whyEmpty(key)) : "";
              return (
                <span
                  key={key}
                  data-field-key={key}
                  //: 宽度上限挂在**这一层**(相对整条底栏的 45%),芯片自己撑满这一层 —— 上限写在芯片上的话,百分比
                  //: 相对的是这层按内容定宽的包装,一来一回把字的宽度压成了 0。
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
        tool && fields.rest.length > 0
          ? {
              attention: fields.attention,
              //: **一张表,一种排法**:常用的在前、不常用的在后,一行一项、标签在左。
              content: (
                <NodeConfigForm
                  compact
                  fields={fields.rest}
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
              label: ability ? tool.label : t(item.run?.status === "succeeded" ? "boardToolRerun" : "boardToolRun"),
              hint:
                missing.length > 0
                  ? t("boardToolMissing").replace("{fields}", missing.join(t("listSeparator")))
                  : t(ability ? "boardToolOutputsHint" : "boardGeneratorHint"),
              onSend: send,
              disabled: blocked,
              working,
            }
          : null
      }
    >
      {tool === undefined ? (
        <div role="status" className="flex items-center gap-2 px-1 py-2 text-ui-xs text-muted-foreground">
          <Loader2 size={13} className="animate-spin" /> {t("boardAbilityLoading")}
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
          {ability ? <AbilityHost item={item} tool={tool} /> : null}
          {fields.body ? (
            <textarea
              data-field-key={fields.body[0]}
              aria-label={fieldLabel(...fields.body)}
              value={String(config[fields.body[0]] ?? "")}
              onChange={(event) => setConfig(fields.body![0], event.target.value)}
              rows={fields.body[1].multiline ? 4 : 3}
              placeholder={bodyPlaceholder(t, ...fields.body)}
              className="nowheel w-full resize-none border-0 bg-transparent px-1 py-1 text-ui-sm leading-relaxed text-foreground outline-none placeholder:text-muted-foreground"
            />
          ) : !ability && tool.board_description ? (
            //: 没有要写的字:正文是这个生成器那一句说明(给创作者看的「它做出什么」)。
            <p className="m-0 px-1 py-1 text-ui-sm leading-relaxed text-muted-foreground">
              <InlineMarkdown text={tool.board_description} />
            </p>
          ) : null}
          {failed ? (
            <p role="alert" data-ability-failed="" className="m-0 px-1 text-ui-xs leading-relaxed text-destructive">
              {t("boardNodeRunFailed")} · {failed}
            </p>
          ) : null}
          {missingConnection ? (
            <p data-tool-connection="" className="m-0 flex items-start gap-1.5 px-1 text-ui-xs leading-relaxed text-muted-foreground">
              <PlugZap size={13} className="mt-0.5 shrink-0" />
              <span role="alert" className="text-foreground">
                {t("boardToolNoConnection").replace("{plugin}", tool.plugin_name ?? "")}{" "}
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

/**
 * 正文最上面那一行:**这一下对这一格做什么**。宿主那一格(图片是一张小图,别的是它那种格子的图标)和它的名字,
 * 下面一句工具给创作者看的说明(第一句,纯文字)—— 「把音频或视频里说的话转成文字」,结果新建在右边。
 */
function AbilityHost({ item, tool }: { item: BoardItem; tool: BoardProducerInfo }) {
  const t = useI18n();
  const Icon = boardToolIcon(tool);
  const KindIcon = kindIcon(item.kind);
  const what = firstSentence(tool.board_description ?? "") || tool.label;
  return (
    <div data-ability-host={item.id} className="flex min-w-0 items-center gap-2.5 px-1 py-1">
      <div className="grid h-10 w-14 shrink-0 place-items-center overflow-hidden rounded-md border border-border bg-secondary/40 text-muted-foreground">
        {item.kind === "image" && item.asset_id ? (
          <AssetInlinePreview
            key={item.asset_id}
            assetId={item.asset_id}
            name={sourceName(t, item)}
            kind="image"
            plain
            previewOnClick={false}
            lazy={false}
            imageFallback={<KindIcon size={16} strokeWidth={1.4} />}
            className="h-full w-full object-cover"
          />
        ) : (
          <KindIcon size={16} strokeWidth={1.4} />
        )}
      </div>
      <div className="grid min-w-0 flex-1 gap-0.5">
        <span data-ability-host-name="" className="flex min-w-0 items-center gap-1.5 text-ui-sm text-foreground">
          <Icon size={13} className="shrink-0 text-primary" />
          <span className="truncate">{tool.label}</span>
          <span className="shrink-0 text-muted-foreground">·</span>
          <span className="truncate text-muted-foreground">{sourceName(t, item)}</span>
        </span>
        <span data-ability-what="" className="line-clamp-2 text-ui-xs leading-snug text-muted-foreground">
          {what}
        </span>
      </div>
    </div>
  );
}

/** 正文的占位:这一格要写什么(字段自己的说明,第一句),没有说明时是「写下{字段}」—— 不是光秃秃的字段名
 *  (「文本」「Key」读起来像一个没填的表单标签)。 */
function bodyPlaceholder(t: (key: MessageKey) => string, key: string, spec: BoardFieldSpec): string {
  const said = spec.description ? firstSentence(toPlainText(String(spec.description))) : "";
  return said || t("boardToolBodyPlaceholder").replace("{field}", String(spec.label || key));
}
