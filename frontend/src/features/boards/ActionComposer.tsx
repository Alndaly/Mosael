import React from "react";
import { NodeToolbar, Position } from "@xyflow/react";
import { useQuery } from "@tanstack/react-query";
import { ChevronDown, Link2, Loader2, Play, PlugZap } from "lucide-react";

import { fetchWorkflowFieldOptions, type BoardItem, type BoardProducerInfo, type BoardRunForms } from "@/api/client";
import { useI18n } from "@/app/preferences";
import { CANVAS_WINDOW_SURFACE_CLASS } from "@/components/app/canvasPanelLayout";
import { InlineMarkdown } from "@/components/markdown/InlineMarkdown";
import { BOARD_NODE_PANEL_OFFSET } from "@/features/boards/boardLayout";
import { kindIcon, kindText } from "@/features/boards/boardNodes";
import { useSubmitting } from "@/features/boards/useSubmitting";
import {
  NodeConfigForm,
  nodeConfigTiers,
  useNodeFieldOptions,
  type ConfigSpec,
  type FieldBinding,
} from "@/features/nodeForms/NodeConfigForm";
import { cn } from "@/lib/utils";

type Form = BoardRunForms["node"];

/** 「这个人的插件连接」那种选项的来源名(后端 field_options 的 plugin_instances)。 */
const CONNECTION_SOURCE = "plugin_instances";
type Bindings = Form["bindings"];

/** 工具清单里一个字段的声明:节点表单那一份 + 画板多给的一样 —— 它能接哪几种上游格子。 */
type BoardFieldSpec = ConfigSpec & { board_sources?: string[] };

/**
 * 上游这一格**能不能给出值**。还没有产出的空槽(图片还在生成、文档还没挑)接上去也取不到东西 ——
 * 服务端运行时照样会跳过它,这里就不把它列成一个可以点的选项。
 */
function givesValue(item: BoardItem): boolean {
  if (item.kind === "note") return true;
  if (item.kind === "document") return Boolean(item.note_id);
  if (item.kind === "scene") return Boolean(item.scene_id);
  return Boolean(item.asset_id);
}

/** 绑定芯片上怎么称呼上游那一格:起了名用名字;便签没起名就用开头几个字(几张便签都叫「便签」分不开)。 */
function sourceName(t: ReturnType<typeof useI18n>, item: BoardItem): string {
  const title = item.title?.trim();
  if (title) return title;
  if (item.kind === "note" && item.text?.trim()) {
    const text = item.text.trim().replace(/\s+/g, " ");
    return text.length > 18 ? `${text.slice(0, 18)}…` : text;
  }
  if (item.kind === "document" && item.text?.trim()) return item.text.trim();
  return kindText(t, item.kind).label;
}

/** 这个字段收一串还是一份:文字字段(多张便签按连线顺序拼起来)和复数的素材字段收一串。 */
function takesMany(key: string, spec: BoardFieldSpec): boolean {
  return Boolean(spec.board_sources?.includes("note")) || /(^|_)asset_ids$/.test(key);
}

/**
 * 一格上游 → 接到哪些字段的默认绑定:**必填**、能接上游、还没绑也没手填过的字段,绑第一个接得上的上游。
 *
 * 「没手填过」看的是 config 里有没有这个键 —— 用户把它切回「手填」时,面板会把它写成空串
 * (见 setBound),于是不会刚解开就又被绑回去。返回 null 表示不用改。
 */
export function defaultBindings(
  specs: Record<string, BoardFieldSpec>,
  config: Record<string, unknown>,
  bindings: Bindings,
  sources: BoardItem[],
): Bindings | null {
  let next: Bindings | null = null;
  for (const [key, spec] of Object.entries(specs)) {
    if (!spec?.required || !spec.board_sources?.length) continue;
    if (bindings[key]?.length || key in config) continue;
    const first = sources.find((one) => spec.board_sources?.includes(one.kind) && givesValue(one));
    if (!first) continue;
    next = { ...(next ?? bindings), [key]: [{ from: first.id }] };
  }
  return next;
}

/**
 * 工具格的面板:跑一个插件工具或工作流节点。
 *
 * **表单不是为这一个工具写的。** 字段、下拉、基础 / 高级分档全由节点声明说了算,渲染用的是工作流
 * 检查器那一份 NodeConfigForm —— 这里不认识任何具体节点(棘轮 nodeInspectorIsNodeAgnostic)。
 * 画板只补自己那一半:
 *
 *  · **字段接上游**。工作流里模板字段写 `{{上游.输出}}`;画板上没有「输出」可引用,上游是连进来的
 *    那几格 —— 所以接上游的字段显示成一排芯片,点哪一格就从哪一格取(便签给字、文档给正文、
 *    图片/视频/音频给素材、3D 场景给场景)。哪种格子能接哪个字段由后端说(`board_sources`)。
 *    必填的字段默认绑第一个接得上的上游,可以改,改了存在这一格上。值在运行时由服务端从画布上取:
 *    上游改了字,下次运行就跟着变。
 *  · **用谁的连接**。插件工具跑的是点运行的这个人自己接的连接 —— 共享画板上尤其如此。面板写明
 *    「将用你的连接「X」运行」;没有就说清楚、给一个去插件页的入口。
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
  const fieldOptions = useNodeFieldOptions({ specs, config, workspaceId, nodeType });
  const { submitting, run } = useSubmitting();
  const working = submitting || busy;
  const [showAdvanced, setShowAdvanced] = React.useState(false);

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
  const chosen = String(config[connectionKey] ?? "");
  const available = connections.data ?? [];
  const connection = connectionSpec?.options_from
    ? available.find((one) => one.value === chosen) ?? (!chosen && available.length === 1 ? available[0] : undefined)
    : undefined;
  const missingConnection = Boolean(connectionSpec?.options_from) && connections.isSuccess && available.length === 0;

  const fits = (key: string) =>
    sources.filter((one) => specs[key]?.board_sources?.includes(one.kind) && givesValue(one));
  const binding: FieldBinding = {
    canBind: (key) => fits(key).length > 0 || Boolean(bindings[key]?.length),
    isBound: (key) => Boolean(bindings[key]?.length),
    setBound: (key, bound) => {
      if (bound) {
        const first = fits(key)[0];
        if (first) save({ bindings: { ...bindings, [key]: [{ from: first.id }] } });
        return;
      }
      const { [key]: _dropped, ...rest } = bindings;
      //: 切回手填:把这个键写进 config(空串也算),默认绑定就不会刚解开又绑回去。
      save({ bindings: rest, config: key in config ? config : { ...config, [key]: "" } });
    },
    renderBound: (key) => {
      const spec = specs[key] ?? {};
      const picked = new Set((bindings[key] ?? []).map((one) => one.from));
      const options = fits(key);
      const many = takesMany(key, spec);
      if (options.length === 0) {
        return <span className="text-ui-2xs text-muted-foreground">{t("boardToolNoUpstreamFit")}</span>;
      }
      return (
        <div role="group" aria-label={t("boardToolPickUpstream")} data-binding-chips={key} className="flex flex-wrap gap-1.5">
          {options.map((source) => {
            const Icon = kindIcon(source.kind);
            const on = picked.has(source.id);
            return (
              <button
                key={source.id}
                type="button"
                aria-pressed={on}
                data-binding-source={source.id}
                title={sourceName(t, source)}
                className={cn(
                  "inline-flex max-w-full cursor-pointer items-center gap-1 rounded-full border px-2 py-0.5 text-ui-2xs transition-colors",
                  on
                    ? "border-[color-mix(in_srgb,var(--primary)_45%,transparent)] bg-[color-mix(in_srgb,var(--primary)_10%,transparent)] text-primary"
                    : "border-border text-muted-foreground hover:border-border-strong hover:text-foreground",
                )}
                onClick={() => {
                  const current = bindings[key] ?? [];
                  const next = on
                    ? current.filter((one) => one.from !== source.id)
                    : many
                      ? [...current, { from: source.id }]
                      : [{ from: source.id }];
                  if (next.length === 0) binding.setBound(key, false);
                  else save({ bindings: { ...bindings, [key]: next } });
                }}
              >
                <Icon size={11} className="shrink-0" />
                <span className="truncate">{sourceName(t, source)}</span>
              </button>
            );
          })}
        </div>
      );
    },
  };

  const { basic, advanced } = nodeConfigTiers(specs, config);
  const setConfig = (key: string, value: unknown) => save({ config: { ...config, [key]: value } });

  const blocked = !tool || missingConnection || working;
  const send = () => {
    if (blocked) return;
    run(() => onRun({ config, bindings }));
  };

  return (
    <NodeToolbar nodeId={item.id} isVisible position={Position.Bottom} offset={BOARD_NODE_PANEL_OFFSET}>
      <div
        data-action-composer=""
        className={cn(CANVAS_WINDOW_SURFACE_CLASS, "nodrag nopan nowheel grid max-h-[min(520px,70vh)] w-[400px] gap-3 overflow-y-auto p-3")}
      >
        {tool === undefined ? (
          <div role="status" className="flex items-center gap-2 text-ui-xs text-muted-foreground">
            <Loader2 size={13} className="animate-spin" /> {t("boardKindAction")}
          </div>
        ) : tool === null ? (
          <p role="alert" className="text-ui-xs leading-relaxed text-muted-foreground">
            {t("boardToolUnavailable")}{" "}
            <a href="#/plugins" className="text-primary underline-offset-2 hover:underline">
              {t("boardToolOpenPlugins")}
            </a>
          </p>
        ) : (
          <>
            {/* 画板那一句说明(给创作者看的「它把内容变成什么」),不是工作流节点那段写给搭流程的人的。 */}
            {tool.board_description && (
              <p className="text-ui-xs leading-relaxed text-muted-foreground">
                <InlineMarkdown text={tool.board_description} />
              </p>
            )}
            {connectionSpec?.options_from && (
              <div data-tool-connection="" className="flex items-start gap-1.5 text-ui-2xs leading-relaxed">
                <PlugZap size={12} className="mt-0.5 shrink-0 text-muted-foreground" />
                {missingConnection ? (
                  <span role="alert" className="text-foreground">
                    {t("boardToolNoConnection").replace("{plugin}", plugin)}{" "}
                    <a href="#/plugins" className="text-primary underline-offset-2 hover:underline">
                      {t("boardToolOpenPlugins")}
                    </a>
                  </span>
                ) : connection ? (
                  <span className="text-muted-foreground">{t("boardToolConnection").replace("{name}", connection.label)}</span>
                ) : connections.isSuccess ? (
                  <span className="text-muted-foreground">{t("boardToolPickConnection").replace("{plugin}", plugin)}</span>
                ) : null}
              </div>
            )}
            {basic.length > 0 && (
              <div className="grid gap-3">
                <NodeConfigForm
                  fields={basic}
                  config={config}
                  workspaceId={workspaceId}
                  variables={[]}
                  fieldOptions={fieldOptions}
                  onSetConfig={setConfig}
                  onTypeConfig={setConfig}
                  binding={binding}
                />
              </div>
            )}
            {advanced.length > 0 && (
              <div className="grid gap-3">
                <button
                  type="button"
                  aria-expanded={showAdvanced}
                  onClick={() => setShowAdvanced((open) => !open)}
                  className="inline-flex w-fit cursor-pointer items-center gap-1 text-ui-2xs text-muted-foreground hover:text-foreground"
                >
                  <ChevronDown size={12} className={cn("transition-transform", showAdvanced ? "" : "-rotate-90")} />
                  {t("wfAdvanced")}
                </button>
                {showAdvanced && (
                  <NodeConfigForm
                    fields={advanced}
                    config={config}
                    workspaceId={workspaceId}
                    variables={[]}
                    fieldOptions={fieldOptions}
                    onSetConfig={setConfig}
                    onTypeConfig={setConfig}
                    binding={binding}
                  />
                )}
              </div>
            )}
            <div className="flex items-center gap-2 border-t border-border pt-2.5">
              <span className="flex min-w-0 flex-1 items-center gap-1 text-ui-2xs text-muted-foreground">
                <Link2 size={11} className="shrink-0" />
                <span className="truncate" title={t("boardToolOutputsHint")}>{t("boardToolOutputsHint")}</span>
              </span>
              <button
                type="button"
                data-board-tool-run=""
                disabled={blocked}
                onClick={send}
                className={cn(
                  "flex h-7 shrink-0 items-center gap-1 rounded-full px-3 text-ui-2xs transition-colors",
                  blocked
                    ? "cursor-not-allowed bg-secondary text-muted-foreground"
                    : "cursor-pointer bg-action text-action-foreground hover:opacity-90",
                )}
              >
                {working ? <Loader2 size={12} className="animate-spin" /> : <Play size={12} />}
                {t(item.run?.status === "succeeded" ? "boardToolRerun" : "boardToolRun")}
              </button>
            </div>
          </>
        )}
      </div>
    </NodeToolbar>
  );
}
