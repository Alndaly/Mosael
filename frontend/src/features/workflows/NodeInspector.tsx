import React from "react";
import { useQuery } from "@tanstack/react-query";
import { NodeToolbar, Position } from "@xyflow/react";
import { AlertTriangle, Boxes, Trash2, Type, X } from "lucide-react";
import { toast } from "sonner";

import {
  listProviderDefaults,
  listProviderProfiles,
  type WorkflowGraph,
  type WorkflowNodeType,
} from "@/api/client";
import { providerKeys } from "@/api/queryKeys";
import type { MessageKey } from "@/app/messages";
import { useI18n } from "@/app/preferences";
import { Combobox } from "@/components/app/combobox";
import { ConfigNotice, Notice } from "@/components/app/ConfigNotice";
import { InlineMarkdown } from "@/components/markdown/InlineMarkdown";
import { MODAL_SURFACE } from "@/components/ui/floating";
import { IconButton } from "@/components/ui/icon-button";
import { MenuContent, MenuItem } from "@/components/ui/menu";
import { Popover, PopoverTrigger } from "@/components/ui/popover";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { dependentsCleared, withDependentsCleared } from "@/features/nodeForms/dependents";
import { RefCatalogContext, refLabel } from "@/features/nodeForms/refCatalog";
import { bareRef } from "@/features/nodeForms/refDoc";
import { refProblemText } from "@/features/nodeForms/refLook";
import { RefToken } from "@/features/nodeForms/RefToken";
import {
  FIELD_BOX,
  NodeConfigForm,
  nodeConfigTiers,
  useNodeFieldOptions,
  type ConfigSpec,
  type FieldBinding,
} from "@/features/nodeForms/NodeConfigForm";
import { bodyScope, drivesDigitalHuman, extractRefs, isCodeConfig, isNestedScopeConfig } from "@/features/workflows/analyze";
import { chatProfileIds, generationVendors } from "@/features/workflows/bindingReadiness";
import { withDataInputBound } from "@/features/workflows/connections";
import { GENERATE_SPECIAL_CONFIG_KEYS, generateNodeSection, useGenerateNodeSection } from "@/features/workflows/nodeInspectorGenerate";
import { LLM_SPECIAL_CONFIG_KEYS, llmAdvancedSection, llmPresetSection } from "@/features/workflows/nodeInspectorLlm";
import { RunOutputs } from "@/features/workflows/RunOutputs";
import type { Step } from "@/features/workflows/runSteps";
import { bodyKey, bodyVariables, declaredFieldNames } from "@/features/workflows/scope";
import { workflowNodeVisual } from "@/features/workflows/WorkflowNode";
import { useUnusableNodeReasons } from "@/features/workflows/useUnusableNodeReasons";
import { workflowRefCatalog } from "@/features/workflows/workflowRefCatalog";
import { unknownNodeTypeText } from "@/features/workflows/workflowCanvasModel";
import type { SetGraphOptions } from "@/features/workflows/workflowGraphStore";
import { EMPTY_SCOPE_VARIABLES } from "@/features/workflows/workflowViewShared";
import { GENERATION_KINDS, type GenerationKind } from "@/lib/generationCapabilities";
import { useGenerationOptions } from "@/lib/generationOptions";
import { GENERATION_KIND_LABELS } from "@/lib/generationParameterLabels";
import { isTypingTarget, listenKeys } from "@/lib/shortcuts";
import { cn } from "@/lib/utils";

//: 选中节点的检查器:节点上方的分段条 + 节点下方的面板。字段怎么渲染在 features/nodeForms,
//: 生成 / 大模型两种节点的专区在 nodeInspectorGenerate / nodeInspectorLlm。

/** 选中节点的所有上游变量(祖先节点输出 + start 参数),供插入器使用。 */
function upstreamVariables(
  graph: WorkflowGraph,
  nodeId: string,
  registry: Map<string, WorkflowNodeType>,
): string[] {
  const parents = new Map<string, string[]>();
  for (const edge of graph.edges) {
    parents.set(edge.target, [...(parents.get(edge.target) ?? []), edge.source]);
  }
  const ancestors = new Set<string>();
  const queue = [...(parents.get(nodeId) ?? [])];
  while (queue.length) {
    const current = queue.pop()!;
    if (ancestors.has(current)) continue;
    ancestors.add(current);
    queue.push(...(parents.get(current) ?? []));
  }
  const refs: string[] = [];
  for (const node of graph.nodes) {
    if (!ancestors.has(node.id)) continue;
    //: 输出名按声明展开:`*params` 这种是「那个配置字段里的每个键」(和容器体的 body_scope 同一种写法)。
    const outputs = declaredFieldNames(registry.get(node.type)?.outputs ?? [], node.config as Record<string, unknown> | undefined);
    for (const output of outputs) refs.push(`{{${node.id}.${output}}}`);
  }
  return refs;
}

const NO_STEPS: Readonly<Record<string, Step>> = {};

export function NodeInspector({
  inert = false,
  step = null,
  runSteps = NO_STEPS,
  node,
  meta,
  graph,
  registry,
  scopeVariables = EMPTY_SCOPE_VARIABLES,
  workspaceId,
  workflowId = "",
  onChange,
  onApplyGraph,
  onDelete,
  onDrillIn,
  onClose,
}: {
  /** 画布正在平移:此时面板不吃指针事件(见 WorkflowsView 里 panning 的说明)。 */
  inert?: boolean;
  /** 这个节点在**最近一次运行**里的那一步。没跑过就是 null。 */
  step?: Step | null;
  /** 最近一次运行里每个节点的那一步(节点 id → 步):引用上游输出时,交回过的字段能直接挑。 */
  runSteps?: Readonly<Record<string, Step>>;
  node: WorkflowGraph["nodes"][number];
  meta: WorkflowNodeType | null;
  graph: WorkflowGraph;
  registry: Map<string, WorkflowNodeType>;
  /** 子图作用域的虚拟变量；它们不是图节点，但在运行时由循环/子图执行器注入。 */
  scopeVariables?: string[];
  workspaceId: string;
  /** 正在编辑的这张图。可调用工作流的清单要把自己排掉;新建、未保存时为空。 */
  workflowId?: string;
  /** `options.coalesce`:这一下属于哪一串打字(见 typingRun);离散的一步不给。 */
  onChange: (patch: Partial<WorkflowGraph["nodes"][number]>, options?: SetGraphOptions) => void;
  onApplyGraph: (next: WorkflowGraph) => void;
  onDelete?: () => void;
  /** 只有子图 / 循环节点给 —— 双击进子画布的那件事,在悬浮键上也给一个入口。 */
  onDrillIn?: () => void;
  onClose?: () => void;
}) {
  const t = useI18n();
  //: 节点类型不在目录里:问后端为什么(就绪清单、画布角标问的是同一份,按类型缓存)。
  const unusableReasons = useUnusableNodeReasons(meta ? [] : [node.type]);
  const nodeVisual = workflowNodeVisual(node.type);
  const config = (node.config ?? {}) as Record<string, unknown>;
  const allSpecs = (meta?.config ?? {}) as Record<string, ConfigSpec>;
  // 每字段的输入方式:手动填写 vs 连接上游输出(ComfyUI 式)。默认从值推断(纯引用=连接)。
  const variables = React.useMemo(
    () => Array.from(new Set([...scopeVariables, ...upstreamVariables(graph, node.id, registry)])),
    [graph, node.id, registry, scopeVariables],
  );
  //: 引用长什么样、指不指得到、底下有哪些字段(表单里「值或上游输出」那一类控件读它,见 nodeForms/refCatalog)。
  const refCatalog = React.useMemo(
    () =>
      workflowRefCatalog({
        graph,
        registry,
        scopeVariables,
        runOutputs: Object.fromEntries(Object.entries(runSteps).map(([id, one]) => [id, one.outputs])),
      }),
    [graph, registry, scopeVariables, runSteps],
  );
  //: 容器自己的 output / condition 在体跑完之后求值,能插的是体里节点的输出(和体的作用域变量),
  //: 不是容器外面的上游 —— 列外层变量的话,选进去的引用运行时一律是空的。
  const fieldVariables = React.useMemo(() => {
    const inner = bodyVariables(node, registry);
    const keys = Object.keys(meta?.config ?? {}).filter(
      (key) => isNestedScopeConfig(registry, node.type, key) && key !== bodyKey(registry, node.type),
    );
    return Object.fromEntries(keys.map((key) => [key, inner]));
  }, [meta, node, registry]);

  // 失效引用:本节点配置里引用了图中已不存在的节点(通常是上游被删)。
  //: 代码字段不查:代码不插值,里面的 {{…}} 是字面文字(就绪清单同一条,见 analyze.isCodeConfig)——
  //: 此前这里照查,报「引用了已删除的节点」,还给一个「重新指向」去改写用户的代码。
  const staleRefs = React.useMemo(() => {
    const ids = new Set(graph.nodes.map((n) => n.id));
    const scopeRoots = new Set(scopeVariables.flatMap((value) => extractRefs(value).map(({ sourceId }) => sourceId)));
    const found: Array<{ key: string; ref: string }> = [];
    for (const [key, val] of Object.entries(node.config ?? {})) {
      if (isNestedScopeConfig(registry, node.type, key) || isCodeConfig(registry, node.type, key)) continue;
      for (const { ref, sourceId } of extractRefs(val)) {
        if (!ids.has(sourceId) && !scopeRoots.has(sourceId) && !found.some((f) => f.key === key && f.ref === ref)) {
          found.push({ key, ref });
        }
      }
    }
    return found;
  }, [node.config, node.type, graph.nodes, scopeVariables, registry]);

  /* LLM 专区仍直接使用连接清单；其它声明了 options_from 的字段统一走 field-options。 */
  const picksChatModel = node.type === "llm";
  // 动态选项源:按需拉取,只有对应节点类型选中时才请求。
  const providers = useQuery({
    queryKey: providerKeys.profiles(),
    queryFn: listProviderProfiles,
    enabled: picksChatModel || node.type === "ai_generate",
  });
  //: 插件的包与工具、发布账号、可调用工作流、对话连接与模型此前各拉一份清单、各写一段过滤,
  //: 现在都由后端按 `options_from` 给(见 domain/workflows/field_options)。
  // 要完整类型:参数区靠 capabilities 决定渲染什么。每种能力各取一次再合并 —— 和 AI 工作台读的是同一份缓存。
  const generationModels = useGenerationOptions(GENERATION_KINDS, { enabled: node.type === "ai_generate" });
  const providerDefaults = useQuery({
    queryKey: providerKeys.defaults(),
    queryFn: listProviderDefaults,
    enabled: node.type === "ai_generate",
  });
  // 选项要现查的字段、素材下拉:由表单那一层按声明去拉(见 features/nodeForms)。
  //: 接了数据边的字段,值是上游的输出 —— 运行时才有。依赖它的下拉(镜头跟着场景)因此说「运行时才知道」,
  //: 而不是拿空值去查一张空清单、再说「先选场景」。
  const boundValues = React.useMemo(
    () => Object.fromEntries((node.inputs ?? []).map((key) => [key, ""])),
    [node.inputs],
  );
  // 绑定校验:节点依赖的模型/服务没配好(空列表)或引用已失效(指向不存在的项)→ 顶部给提醒 + 配置入口。
  //: 判据和就绪清单同一份(bindingReadiness):清单报错的节点,这里也得说得出为什么。
  const bindingNotice = ((): { message: string; section: string; error?: boolean } | null => {
    if (node.type === "llm") {
      const usable = chatProfileIds(providers.data ?? []);
      if (providers.isSuccess && usable.size === 0) return { message: t("wfNoProviders"), section: "providers" };
      const pid = config.profile_id;
      if (typeof pid === "string" && pid && providers.isSuccess && !usable.has(pid))
        return { message: t("wfProviderMissing"), section: "providers", error: true };
    }
    if (node.type === "ai_generate") {
      const chosenProvider = config.provider as string | undefined;
      const chosenModel = config.model as string | undefined;
      const models = generationModels.options;
      const matchedModel = models.find(
        (model) =>
          model.provider === chosenProvider &&
          model.model === chosenModel &&
          (!config.provider_profile_id || model.provider_profile_id === config.provider_profile_id) &&
          (!config.kind || model.kind === config.kind),
      );
      const capability = String(config.kind || matchedModel?.kind || "image");
      const capabilityLabel = t(GENERATION_KIND_LABELS[capability as GenerationKind] ?? "capImage");
      const section = `providers:${capability}`;
      if (chosenProvider && generationModels.loaded && !generationVendors(models).has(chosenProvider)) {
        return { message: t("wfIssueGenUnconfigured"), section, error: true };
      }
      if (chosenProvider && chosenModel && generationModels.loaded && !matchedModel) {
        return { message: t("wfGenModelMissing"), section, error: true };
      }
      //: 默认供应商只在节点**没选**模型时才用得上(后端 generation/operations.create_generation_job:
      //: provider 或 model 为空才取默认)。选好了还提示「还没有默认」,说的是一件与这个节点无关的事。
      if (chosenProvider && chosenModel) return null;
      const defaultForCapability = (providerDefaults.data ?? []).find((item) => item.capability === capability);
      const defaultProfile = defaultForCapability?.provider_profile_id
        ? (providers.data ?? []).find((profile) => profile.id === defaultForCapability.provider_profile_id)
        : null;
      if (
        providerDefaults.isSuccess &&
        providers.isSuccess &&
        (!defaultForCapability?.provider_profile_id || !defaultForCapability.model || !defaultProfile?.enabled)
      ) {
        return {
          message: t("aiCapabilityNotConfigured").replace("{capability}", capabilityLabel),
          section,
        };
      }
    }
    return null;
  })();

  // Esc 收起检查器 —— 输入框/代码编辑器里不劫持(那里 Esc 另有用途)。
  // **也只认画布里发出的 Esc。** 检查器里展开的下拉、弹层是 Portal 到 body 的,那一下 Esc
  // 是「收起这个下拉」,此前却连检查器一起关了(选中也跟着没了)。
  React.useEffect(() => {
    if (!onClose) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      const target = event.target as Element | null;
      if (isTypingTarget(target)) return;
      if (target && target !== target.ownerDocument?.body && !target.closest(".react-flow")) return;
      onClose();
    };
    return listenKeys(window, onKey);
  }, [onClose]);

  // 换了父字段就清掉依赖它的子字段 —— 规则抽在 dependents.ts(有测试),这里只负责接线。
  const setConfig = (key: string, value: unknown, options?: SetGraphOptions) => {
    onChange({ config: withDependentsCleared(config, key, value, allSpecs) }, options);
  };
  /**
   * **打字是连发,不是离散编辑。** 每敲一个字符记一条历史的话,Cmd+Z 一次只退回一个字母。
   * 所以文字输入类控件把改动标成「这个节点这个字段的一串」,在历史里塌成一条(存的是这串开始前
   * 的图,见 workflowGraphStore);换下拉、拨开关不标,一步一条 —— 它们本来就是离散的。
   * 串按字段分:在 A 里打完字紧接着改 B,是两步。
   */
  const typingRun = (field: string): SetGraphOptions => ({ coalesce: `${node.id}.${field}` });
  const typeConfig = (key: string) => (value: unknown) => setConfig(key, value, typingRun(key));
  /** 一个控件一次改好几格(开始节点的参数连同必填清单):一次落进图里,打字的那一串按控件所在的字段塌成一条。 */
  const patchConfig = (owner: string, patch: Record<string, unknown>, typing: boolean) =>
    onChange({ config: { ...config, ...patch } }, typing ? typingRun(owner) : undefined);
  const responseFormat = String(config.response_format || "text");
  const setTextConfig = (key: string) => (event: React.ChangeEvent<HTMLInputElement>) => typeConfig(key)(event.target.value);

  // 重新指向:把某字段里的失效引用整体替换为新引用(空串=移除该引用)。
  const repoint = (key: string, oldRef: string, newRef: string) => {
    setConfig(key, String(config[key] ?? "").split(oldRef).join(newRef));
  };

  // 连接态字段(node.inputs)+ 数据边管理。
  const connectedInputs = node.inputs ?? [];
  // 本节点的后代(顺边正向可达),绑数据边时排除它们避免成环。
  const descendants = React.useMemo(() => {
    const adjacency = new Map<string, string[]>();
    for (const edge of graph.edges) {
      adjacency.set(edge.source, [...(adjacency.get(edge.source) ?? []), edge.target]);
    }
    const seen = new Set<string>();
    const queue = [...(adjacency.get(node.id) ?? [])];
    while (queue.length) {
      const current = queue.pop()!;
      if (seen.has(current)) continue;
      seen.add(current);
      queue.push(...(adjacency.get(current) ?? []));
    }
    return seen;
  }, [graph.edges, node.id]);
  // 可绑定来源:任意非后代、非自身节点的具体输出(数据边本身即建立依赖/排序)。
  //: 通配按那个节点的配置展开 —— 开始节点的每个参数各是一个口(和画布上画口的取法同一份,见 workflowCanvasModel)。
  const upstreamOptions = graph.nodes.flatMap((source) => {
    if (source.id === node.id || descendants.has(source.id)) return [];
    return declaredFieldNames(registry.get(source.type)?.outputs ?? [], source.config as Record<string, unknown> | undefined)
      .map((output) => ({ ref: `{{${source.id}.${output}}}`, sourceId: source.id, output }));
  });
  const dataEdgeFor = (key: string) =>
    graph.edges.find((edge) => edge.kind === "data" && edge.target === node.id && edge.target_input === key) ?? null;

  // 切换字段的连接态:连接=进 inputs;断开=移出 inputs 并删对应数据边。
  //: 依赖它的字段(轨道跟着时间线)只在**值从哪来真的换了**时清:断开一条确实存在的数据边。
  //: 拨到「接上游」那一下还没有边,运行时用的仍是手填的值;接哪条边由 bindInput 定,清在那里。
  const setConnected = (key: string, connected: boolean) => {
    const edge = dataEdgeFor(key);
    //: 断开时连「只有数据边、不在 inputs 里」的也要断得开(智能体改的、旧图):后端认的是那条边。
    if (connected ? connectedInputs.includes(key) : !connectedInputs.includes(key) && !edge) return;
    const unbindsEdge = !connected && edge !== null;
    const inputs = new Set(connectedInputs);
    if (connected) inputs.add(key);
    else inputs.delete(key);
    onApplyGraph({
      ...graph,
      edges: connected
        ? graph.edges
        : graph.edges.filter(
            (edge) => !(edge.kind === "data" && edge.target === node.id && edge.target_input === key),
          ),
      nodes: graph.nodes.map((n) =>
        n.id === node.id
          ? { ...n, inputs: [...inputs], config: unbindsEdge ? dependentsCleared(n.config ?? {}, key, allSpecs) : n.config }
          : n,
      ),
    });
  };

  // 绑定输入到某上游输出:建/换数据边,清字面量交给数据边供值(依赖它的字段一并清掉,见 withDataInputBound)。
  const bindInput = (key: string, sourceId: string, output: string) => {
    onApplyGraph(withDataInputBound(graph, { targetId: node.id, key, sourceId, output }, allSpecs));
  };

  // ── AI 生成节点:所选模型 + 它声明支持的参数 ────────────────────────────────
  const gen = useGenerateNodeSection({ node, config, generationModels, onChange, setConfig, t });
  const { genPromptMode, genSourceRoles } = gen;
  //: 「输入素材」那几格是这里自己画的专区(不走字段声明),它要的素材清单由这里说 —— 画着几格就要,一格没有就不拉。
  const fieldOptions = useNodeFieldOptions({
    specs: allSpecs, config, workspaceId, nodeType: node.type, workflowId, boundValues,
    hostNeeds: { assets: genSourceRoles.length > 0 },
  });

  // 面板真正要渲染的字段:llm / ai_generate 的那几项由各自的专区管,不走通用列表。
  // 顺序就是后端声明的顺序;基础 / 高级的分档规则在表单那一层(nodeConfigTiers)。
  //: 挂了驱动音频(说话照片、对口型,即数字人):授权确认是这一次跑不跑得了的前提 —— 生成漏斗没它当场拒
  //: (genErr_digitalHumanNeedsConsent)。声明里它收在高级(别的生成用不上),这时就不能还藏在那儿:
  //: 提到第一屏、标成必填。判据和就绪清单同一份(analyze.drivesDigitalHuman):这里标必填,清单就拦。
  const digitalHuman = drivesDigitalHuman(node.type, config);
  const panelSpecs =
    node.type === "ai_generate" && allSpecs.prompt
      ? {
          ...allSpecs,
          prompt:
            genPromptMode === "optional"
              ? { ...allSpecs.prompt, description: t("wfGenPromptOptional") }
              : { ...allSpecs.prompt, required: genPromptMode === "required" },
          ...(digitalHuman && allSpecs.consent
            ? { consent: { ...allSpecs.consent, advanced: false, required: true } }
            : {}),
        }
      : allSpecs;
  const { basic: basicSpecs, advanced: advancedSpecs } = nodeConfigTiers(
    panelSpecs,
    config,
    (key) =>
      (node.type === "llm" && LLM_SPECIAL_CONFIG_KEYS.has(key)) ||
      (node.type === "ai_generate" && GENERATE_SPECIAL_CONFIG_KEYS.has(key)) ||
      (node.type === "ai_generate" && key === "prompt" && genPromptMode === "none"),
    (key) => connectedInputs.includes(key),
  );

  // ── 功能区 ──────────────────────────────────────────────────────────────
  // 节点上方那条悬浮键分两组(中间一道竖线):左边是**这个节点有哪几块内容**,点了换下面
  // 面板的内容;右边是**能对这个节点做什么**。
  //
  // 分的是**节点的内容块**,不是表单字段 —— 按字段分会把一份表单切碎(「提示词」「模型」
  // 各自一段),而表单本来就该整份读。参数区里的字段一个不拆。
  //
  // 「预览」不在这儿:产出预览已经通栏长在节点卡片上,面板里再来一份就是同一张图上下叠两遍。
  const areas: string[] = [];
  if (basicSpecs.length > 0) areas.push("config");
  // 「高级」自成一档,而不是正文底下一个折叠块:折叠块把「有没有更多可调的」藏在一次点击后面,
  // 而条上摆着就一眼看得见。**有才出** —— 没有高级项的节点条上不会多这一档。
  if (advancedSpecs.length > 0) areas.push("advanced");
  //: 输出名按声明展开,和变量插入器(upstreamVariables)同一种取法:开始节点声明的是 `*params`
  //: (「params 里的每个键」),原样列出来就是一个引用不到任何东西的 `{{start.*params}}`。
  const outputNames = meta ? declaredFieldNames(meta.outputs, config) : [];
  if (outputNames.length > 0) areas.push("outputs");
  if (step) areas.push("run");
  // 选区属于节点。切到另一个也有“高级/输出”的节点时，不能沿用上一节点停留的页签；否则新节点
  // 一打开就跳过基础参数，像是表单缺了一截。把节点 id 和选区一起存，派生时同步回第一块且不慢一帧。
  const [picked, setPicked] = React.useState<{ nodeId: string; area: string } | null>(null);
  const pickedArea = picked?.nodeId === node.id ? picked.area : null;
  // 派生而不是同步:换节点时 areas 变了,上一个节点选中的那块可能根本不存在 —— 直接回落到
  // 第一块,不需要一个 effect 追着清空(那种 effect 总慢一帧,会先露出一个空面板)。
  const area = pickedArea && areas.includes(pickedArea) ? pickedArea : areas[0];
  const AREA_LABELS: Record<string, MessageKey> = { config: "wfaConfig", advanced: "wfAdvanced", outputs: "wfOutputs", run: "wfRunOutputs" };


  /** 字段接上游 = 数据边(ComfyUI 式:暴露输入接点,再从画布拖数据边或下拉选源)。 */
  const binding: FieldBinding = {
    //: 开始节点是入口,前面什么都没有(画布上它连控制入口都没有,见 WorkflowNode)。
    canBind: () => node.type !== "start",
    //: 接没接上看两样:连接态(inputs)或者真有一条数据边喂它 —— 后者才是后端认的。
    isBound: (key) => connectedInputs.includes(key) || dataEdgeFor(key) !== null,
    setBound: setConnected,
    renderBound: (key) => {
      const boundEdge = dataEdgeFor(key);
      const boundValue = boundEdge ? `${boundEdge.source}.${boundEdge.source_output}` : "";
      //: 接的是哪个上游输出,和引用同一个样子:「节点标题 · 输出显示名」的标签(RefToken),悬停看路径;
      //: 指不到(输出改了名、插件没装)是错误色,底下说为什么。此前这里摆的是 `link.platform` 这种 id 写法。
      const look = boundValue ? refCatalog.look(boundValue) : null;
      // 上游输出会长到几十条(每个上游节点各带一串):能搜,按名字和路径都搜得到。
      return (
        <div className="grid min-w-0 gap-0.5">
          <Combobox
            value={boundValue}
            onValueChange={(next) => {
              const dot = next.indexOf(".");
              bindInput(key, next.slice(0, dot), next.slice(dot + 1));
            }}
            options={upstreamOptions.map((option) => {
              const path = `${option.sourceId}.${option.output}`;
              return { value: path, label: refLabel(refCatalog.look(path)) };
            })}
            renderValue={() => (look ? <RefToken path={boundValue} look={look} /> : undefined)}
            placeholder={t("wfPickUpstream")}
            emptyText={t("cmdkEmpty")}
            className={cn("w-full", look?.problem && "border-destructive")}
          />
          {look?.problem && (
            <small className="text-ui-2xs leading-[1.4] text-destructive" role="alert">
              {refProblemText(t, look.problem)}
            </small>
          )}
        </div>
      );
    },
  };

  /** 表单不认识的那一种字段:内嵌子图(循环体 / 子图),只给只读概览。 */
  const renderOwnField = (key: string, spec: ConfigSpec): React.ReactNode | null => {
    // 循环体 / 子图都是内嵌子图(graph 类型):不铺原始 JSON 文本框,给个只读概览(子画布编辑见 L3)。
    if (spec?.type === "graph") {
      const bodyNodes = ((config[key] as { nodes?: unknown[] } | undefined)?.nodes ?? []).length;
      //: 叫「循环体」还是「子图」,和后端 _body_label 同一个判据:体里有没有 `loop` 这个作用域。
      const isSubgraph = !bodyScope(registry, node.type).includes("loop");
      return (
        <div className={FIELD_BOX} key={key}>
          <label>{t(isSubgraph ? "wfSubgraphBody" : "wfLoopBody")}</label>
          <div className="rounded-md border border-dashed border-border bg-muted px-2.5 py-2 text-ui-xs leading-normal text-muted-foreground">{t(isSubgraph ? "wfSubgraphBodyNote" : "wfLoopBodyNote").replace("{n}", String(bodyNodes))}</div>
        </div>
      );
    }
    return null;
  };

  const renderFields = (fields: Array<[string, ConfigSpec]>) => (
    <NodeConfigForm
      fields={fields}
      config={config}
      workspaceId={workspaceId}
      variables={variables}
      fieldVariables={fieldVariables}
      fieldOptions={fieldOptions}
      onSetConfig={(key, value) => setConfig(key, value)}
      onTypeConfig={(key, value) => typeConfig(key)(value)}
      onPatchConfig={patchConfig}
      binding={binding}
      renderOwnField={renderOwnField}
      references
    />
  );

  /**
   * **住在画布里,大小不跟着缩放变。**
   *
   * 此前它是 position:fixed 的屏幕层浮层,而节点在画布坐标系里 —— 两个坐标系,于是每次平移
   * 缩放都要把节点位置换算成屏幕位置、再夹进窗口。那套换算前后修了三轮:四条边一起越界
   * (摆放按 320 算而面板其实是 380)、拿"高度上限"当实际高度用、子图漏传参数整个走成另一种
   * 样式。三条都是同一个错配的不同发作点。
   *
   * NodeToolbar 正是这件事的原语:渲染在 react-flow 的 viewport portal 里(**和节点同层**),
   * 位置用 viewport.zoom 算所以跟着节点走,但元素本身不缩放 —— 缩到 40% 时面板还是这么大、
   * 还能填表单。换算、四边钳制、量高度那一整套因此全部删掉。
   */
  return (
    <RefCatalogContext.Provider value={refCatalog}>
    {/* 节点悬浮键,分两组、中间一道竖线(tapnow 那条也是这么断的):
          左边 = **这个节点有哪几块内容**(点了换下面面板的内容),右边 = **能对它做什么**。
        两组都按"有才出":没跑过就没有「本次产出」,不是子图就没有「进入子图」。
        和面板一样长在画布坐标系里,所以同样要挂 nodrag/nopan —— 不然按下去是在拖节点。 */}
    <NodeToolbar nodeId={node.id} isVisible position={Position.Top} align="center" offset={12}>
      <div className="nodrag nopan nokey flex items-center gap-1 rounded-full border border-floating-border bg-panel p-1.5 shadow-[var(--shadow-panel)]">
        {areas.map((id) => (
          <button
            key={id}
            type="button"
            className={cn(
              "cursor-pointer rounded-full px-2.5 py-1.5 text-ui-xs font-medium transition-[background,color] duration-100",
              area === id
                ? "bg-secondary text-foreground"
                : "text-muted-foreground hover:bg-secondary hover:text-foreground",
            )}
            aria-pressed={area === id}
            onClick={() => setPicked({ nodeId: node.id, area: id })}
          >
            {t(AREA_LABELS[id])}
          </button>
        ))}
        {/* 竖线只在两边都有东西时才画 —— 否则它分隔的是"一组和空气"。 */}
        {areas.length > 0 && (onDrillIn || onDelete) && (
          <span aria-hidden className="mx-1 h-4 w-px bg-border" />
        )}
        {onDrillIn && (
          <IconButton
            unstyled
            type="button"
            className="grid h-7 w-7 cursor-pointer place-items-center rounded-full text-muted-foreground transition-[background,color] duration-100 hover:bg-secondary hover:text-foreground"
            label={t("wfaEnterSubgraph")}
            onClick={onDrillIn}
          >
            <Boxes size={14} />
          </IconButton>
        )}
        {onDelete && (
          <IconButton
            unstyled
            type="button"
            className="grid h-7 w-7 cursor-pointer place-items-center rounded-full text-muted-foreground transition-[background,color] duration-100 hover:bg-[color-mix(in_oklab,var(--destructive)_10%,transparent)] hover:text-destructive"
            label={t("delete")}
            onClick={onDelete}
          >
            <Trash2 size={14} />
          </IconButton>
        )}
      </div>
    </NodeToolbar>
    {/* 面板在节点**正下方**、分段条在正上方 —— 上下夹着节点,而不是挤在右边。
        居中对齐:节点是这两块的锚,偏在一侧看起来像是飘着的另一个东西。 */}
    <NodeToolbar nodeId={node.id} isVisible position={Position.Bottom} align="center" offset={12}>
    <aside
      className={cn(
        MODAL_SURFACE,
        "grid max-h-[min(560px,calc(100dvh-210px))] min-h-0 w-[460px] max-w-[calc(100vw-2rem)] grid-cols-[minmax(0,1fr)] grid-rows-[auto_minmax(0,1fr)] overflow-hidden rounded-xl",
        // **搬进画布之后必须挂这三个。** 面板现在长在 React Flow 里面,而画布自己要监听
        // pointerdown 来平移、滚轮来缩放 —— 不声明的话这些事件在到达输入框之前就被画布截走:
        // 点输入框不聚焦、打字没反应、下拉点不开。此前面板是 fixed 在画布外面的,画布看不到
        // 这些事件,所以从来不需要声明,搬进来才暴露。
        //   nodrag  —— 在面板里按下不要拖动节点/框选
        //   nopan   —— 不要平移画布
        //   nowheel —— 面板内滚动是滚它自己,不是缩放画布
        //   nokey   —— 面板里的按键不是给画布的:焦点停在一颗按钮 / 下拉上时按 Backspace,
        //              React Flow 只放过输入框,别的一律当成「删除选中节点」—— 删的正是在编辑的这个
        // 另外 viewport-portal 整个 user-select:none,面板里要能选中文字得显式改回来。
        "nodrag nopan nowheel nokey select-text",
        inert && "pointer-events-none",
      )}
      aria-label={node.name || meta?.label || node.type}
    >
      <div className="flex min-h-11 items-center justify-between gap-2 border-b border-divider px-3 py-2">
        {/* 节点说明挂在图标上,不占正文一行 —— 那句话每个节点都有,而只在第一次看时有用,
            之后每次打开都要从它上面跨过去才能到真正要改的参数。 */}
        <Tooltip>
          <TooltipTrigger asChild>
            <span
              className="grid h-6 w-6 flex-none cursor-help place-items-center rounded-md bg-[color-mix(in_srgb,var(--wf-node-color,var(--primary))_12%,transparent)] text-[color:var(--wf-node-color,var(--primary))]"
              style={{ "--wf-node-color": nodeVisual.color } as React.CSSProperties}
            >
              {nodeVisual.icon ?? <Type size={13} />}
            </span>
          </TooltipTrigger>
          {/* 类型和说明都在这里。类型此前是头部的第二行 —— 而**图标已经在表达类型**
              (每种节点各有颜色和图形),再写一遍只是让头部高了一倍。 */}
          <TooltipContent className="grid max-w-[260px] gap-1">
            <span className="font-semibold">{meta?.label ?? node.type}</span>
            {meta?.description && (
              <span className="text-ui-xs opacity-80">
                <InlineMarkdown text={meta.description} links={false} />
              </span>
            )}
          </TooltipContent>
        </Tooltip>
        <div className="grid min-w-0 flex-1 gap-0 [&_small]:pl-0 [&_small]:text-ui-2xs [&_small]:text-muted-foreground">
          {/* 节点名在头部内联编辑(Dify 式),不再单列一个"节点名称"字段。
              **裸 input**:Input 基础款的 border-field-border / rounded-md / h-9 都要对抗,
              而 tokens.css 里那条 `* { border-color: var(--border) }` 和单个 border-* 类
              同优先级、靠顺序决胜 —— 想让边框透明是打不赢的(SubtitlePanel 早就踩过)。

              所以**零边框**,用背景说状态:静止就是标题,悬停浅底(这儿能改),
              聚焦垫底 + ring(正在改)。 */}
          <input
            className="-ml-1 h-7 min-w-0 rounded-md border-0 bg-transparent px-1.5 text-ui-sm font-medium text-foreground outline-none transition-colors duration-100 placeholder:font-normal placeholder:text-muted-foreground hover:bg-[color-mix(in_oklab,var(--foreground)_5%,transparent)] focus-visible:bg-field focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
            value={node.name ?? ""}
            placeholder={meta?.label ?? node.type}
            aria-label={t("wfNodeName")}
            onChange={(event) => onChange({ name: event.target.value }, typingRun("name"))}
          />
        </div>
        {/* 删除在上方悬浮键的操作组里 —— 一个动作只该有一个入口。 */}
        {onClose && (
          <IconButton unstyled type="button" className="grid h-6 w-6 cursor-pointer place-items-center rounded-md border-0 bg-transparent text-muted-foreground transition-[color,background] duration-100 hover:bg-secondary hover:text-foreground" label={t("close")} shortcut="Esc" onClick={onClose}>
            <X size={14} />
          </IconButton>
        )}
      </div>
      <div className="grid min-h-0 grid-cols-[minmax(0,1fr)] content-start gap-3 overflow-x-hidden overflow-y-auto p-3">
        {bindingNotice && (
          <ConfigNotice
            message={bindingNotice.message}
            actionLabel={t("wfGoConfigure")}
            section={bindingNotice.section}
            tone={bindingNotice.error ? "error" : "warn"}
          />
        )}
        {/* 节点类型不在目录里:下面一个字段都画不出来,得说为什么(就绪清单里是同一句)。 */}
        {!meta && <Notice tone="error" message={unknownNodeTypeText(t, node.type, unusableReasons)} />}
        {staleRefs.length > 0 && (
          <div className="flex flex-col gap-1.5 rounded-md border border-[color-mix(in_srgb,var(--destructive)_40%,var(--border))] bg-[color-mix(in_srgb,var(--destructive)_6%,transparent)] px-2.5 py-2">
            <span className="flex items-center gap-[5px] text-ui-xs font-semibold text-destructive">
              <AlertTriangle size={12} /> {t("wfStaleRefsTitle")}
            </span>
            {staleRefs.map(({ key, ref }) => (
              <div className="flex items-center justify-between gap-2" key={`${key}-${ref}`}>
                {/* 和别处的引用同一枚标签:指不到的是错误态,悬停说为什么 —— 不摆 `{{…}}` 原文。 */}
                <RefToken path={bareRef(ref)} look={refCatalog.look(bareRef(ref))} className="min-w-0" />
                <Popover>
                  <PopoverTrigger asChild>
                    <button type="button" className="flex-none cursor-pointer rounded-md border border-border bg-panel px-2 py-0.5 text-ui-xs text-foreground hover:border-border-strong">
                      {t("wfRepoint")}
                    </button>
                  </PopoverTrigger>
                  {/* 名字(「节点标题 · 输出」)是用户起的,截断;下面一行是存储写法 —— 两个节点同名时,
                      靠它分清指的是哪一个(此前它只在原生 title 里)。 */}
                  <MenuContent label={t("wfRepoint")} align="end">
                    {variables.map((valid) => (
                      <MenuItem
                        key={valid}
                        label={refLabel(refCatalog.look(bareRef(valid)))}
                        truncate
                        description={bareRef(valid)}
                        onClick={() => repoint(key, ref, valid)}
                      />
                    ))}
                    <MenuItem label={t("wfRemoveRef")} destructive onClick={() => repoint(key, ref, "")} />
                  </MenuContent>
                </Popover>
              </div>
            ))}
          </div>
        )}
        {area === "config" && node.type === "ai_generate" &&
          generateNodeSection({
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
          })}
        {area === "config" && node.type === "llm" &&
          llmPresetSection({ t, config, variables, setConfig, setTextConfig, typeConfig, responseFormat })}
        {/* **专区此前完全绕过了 advanced 声明。** llm 的十一个旋钮在 NODE_TYPES 里一直标着
            advanced,而专区把它们和 preset 一股脑铺开 —— 于是那个声明在最需要它的节点上
            等于不存在,面板一打开就是满屏采样参数。这里按声明切开:preset 是"这个节点在做
            什么"的那一档,其余进高级。 */}
        {area === "advanced" && node.type === "llm" &&
          llmAdvancedSection({ t, config, variables, setConfig, setTextConfig, typeConfig, responseFormat })}
        {/* 每一档里的表单**整份一起读**,不再切碎;分档只分到「参数 / 高级 / 输出变量 /
            本次产出」这一层。高级从正文底下的折叠块升成条上的一档 —— 折叠块把「还有没有
            更多可调的」藏在一次点击后面,而条上摆着一眼就看得见。 */}
        {area === "config" && renderFields(basicSpecs)}
        {area === "advanced" && renderFields(advancedSpecs)}
        {area === "outputs" && (
          <div className="grid gap-[5px] pt-0.5 [&>span]:text-ui-xs [&>span]:font-semibold [&>span]:uppercase [&>span]:tracking-[0.05em] [&>span]:text-muted-foreground">
            <span>{t("wfOutputs")}</span>
            <div className="flex flex-wrap gap-1" data-output-refs="">
              {outputNames.map((output) => {
                //: 显示的是引用标签(「节点标题 · 输出」);点一下复制的仍是存储写法 —— 贴进别的字段就是一条引用。
                const path = `${node.id}.${output}`;
                const look = refCatalog.look(path);
                const name = refLabel(look);
                return (
                  <IconButton
                    unstyled
                    key={output}
                    type="button"
                    className="cursor-copy rounded-md border-0 bg-transparent p-0"
                    label={t("wfCopyRef").replace("{name}", name)}
                    onClick={() => {
                      void navigator.clipboard.writeText(`{{${path}}}`);
                      toast.success(t("wfRefCopied"), { description: name });
                    }}
                  >
                    <RefToken path={path} look={look} className="pointer-events-none" />
                  </IconButton>
                );
              })}
            </div>
          </div>
        )}
        {/* 「输出变量」列的是**名字**,这里是**这次的值** —— 调工作流时真正要问的是后者。 */}
        {area === "run" && step && <RunOutputs registry={registry} nodeType={node.type} step={step} />}
      </div>
    </aside>
    </NodeToolbar>
    </RefCatalogContext.Provider>
  );
}
