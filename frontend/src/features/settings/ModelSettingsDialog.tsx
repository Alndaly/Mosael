import React from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ChevronDown, ChevronLeft } from "lucide-react";

import { api } from "@/api/client";
import type { components } from "@/api/generated/schema";
import { useI18n } from "@/app/preferences";
import { ModalShell } from "@/components/app/modals";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { OptionPicker } from "@/components/ui/option-picker";
import { Switch } from "@/components/ui/switch";
import { GENERATION_KINDS, type GenerationKind } from "@/lib/generationCapabilities";
import { cn } from "@/lib/utils";

import { CapabilityProfileForm, ProfileField } from "./GenerationProfileForm";

type ModelSettings = components["schemas"]["ProviderModelOut"];

/** 草稿态:读模型回包里每个 kind 都是非空串,而编辑中 null 表示"这个 kind 改回跟随目录"
    (更新载荷 ProviderModelUpdate 允许 null)。共用同一个 state,所以这里显式放宽。 */
type ModelSettingsDraft = Omit<ModelSettings, "generation_capability_refs"> & {
  generation_capability_refs?: Record<string, string | null>;
};

/**
 * 单个模型的设置。
 *
 * **为什么需要**:模型的上下文窗口决定了聊多久开始压缩,而唯一来源是供应商 `/models` 目录 ——
 * 自定义模型名、别名、私有部署经常查不到,于是 128k 的模型被按保守的 32k 用。
 *
 * **只有一项是基本项**。上下文长度是大多数人真会去动的那个(它直接决定"能聊多久"),其余
 * 三个是排障开关:端点报了 400 才需要来翻。全摊开会让这个弹窗看起来像一份要填的表单,
 * 而它其实绝大多数时候一个字都不用改。
 */

type VendorPreset = components["schemas"]["VendorPresetOut"];

/**
 * 可选能力**由后端的 vendor 预设给**,不在这里手抄一份。
 *
 * 抄一份的代价刚兑现过:这里曾照着 `provider_defaults.CAPABILITIES` 写死五项,而模型行认的是
 * `providers.ALL_CAPABILITY_IDS` 六项 —— 于是 embedding 在列表行上有标签、在弹窗里却根本没有
 * 对应的格子,既看不到也改不了。
 *
 * 用**这个 vendor 的**预设而不是全集,还顺带解决了另一半:给纯生图的端点列 chat/tts、
 * 给 DeepSeek 端点列 video,都是让人多读几个不可能的选项。而它正是"未指定时跟随预设"里的
 * 那个预设,所以弹窗里的格子和它下面那句提示永远说的是同一件事。
 */
function useCapabilityOptions(vendor: string | undefined): string[] {
  const presets = useQuery({
    queryKey: ["provider-vendors"],
    queryFn: () => api<VendorPreset[]>("/api/settings/provider-vendors"),
    staleTime: 300_000,
  });
  return React.useMemo(() => {
    const all = presets.data ?? [];
    const mine = all.find((preset) => preset.vendor === vendor);
    if (mine?.capability_ids?.length) return mine.capability_ids;
    // 认不出 vendor(老数据/自定义)就给全集,而不是给空 —— 宁可多几个选项,不能让人改不了。
    const union: string[] = [];
    for (const preset of all) for (const id of preset.capability_ids ?? []) if (!union.includes(id)) union.push(id);
    return union;
  }, [presets.data, vendor]);
}

function AdvancedToggle({
  label,
  hint,
  value,
  onChange,
}: {
  label: string;
  hint: string;
  value: boolean | null | undefined;
  onChange: (next: boolean | null) => void;
}) {
  const t = useI18n();
  const set = value !== null && value !== undefined;
  return (
    // 每项自带背景与边框,和模型列表里的行、以及其它表单的卡片行一致 —— 四个开关平铺在
    // 一片留白上时,读者要自己在脑子里划分组,而背景把"这是一项"直接说出来。
    <div className="grid grid-cols-[minmax(0,1fr)_auto] items-center gap-3 rounded-md border border-border bg-panel px-3 py-2.5">
      <div className="grid min-w-0 gap-0.5">
        <span className="flex items-center gap-1.5 text-ui-sm font-medium text-foreground">
          {label}
          {/* 设过之后才给「跟随默认」——没设过时它本来就是跟随,常驻只会让人以为漏了什么。 */}
          {set && (
            <button
              type="button"
              className="cursor-pointer border-0 bg-transparent p-0 text-ui-2xs font-normal text-muted-foreground underline-offset-2 hover:text-foreground hover:underline"
              onClick={() => onChange(null)}
            >
              {t("modelSettingsFollowDefault")}
            </button>
          )}
        </span>
        <span className="text-ui-xs leading-[1.45] text-muted-foreground">{hint}</span>
      </div>
      <Switch className="shrink-0" checked={Boolean(value)} onCheckedChange={(next) => onChange(next)} />
    </div>
  );
}

type CapabilityRefs = {
  models: { value: string; provider: string; model: string; parameter_keys: string[] }[];
  profiles: { value: string; profile: string; parameter_keys: string[]; custom?: boolean; id?: string }[];
  /** 什么都不指时,这条通道本身给得出哪几项。**空 = 真的只剩提示词**;非空 = 键知道了,
   *  但没人验证过这个模型收哪些取值。这两种处境要分开说。 */
  fallback_keys?: string[];
};

/**
 * 「这一行的生成参数按什么来」。
 *
 * **为什么需要**:生成参数来自一张静态目录,按 (provider, model, kind) 精确查。那张表只能装
 * 我们查证过的东西,而用户手里有它装不下的知识 —— 手填的别名(`gpt-image-2-client` 就是
 * gpt-image-2)、经另一条中转配的同一个模型。此前这些行一个参数都没有,而用户没有任何地方
 * 可以说明白。旁边那几格(思考、视觉、developer 角色)早就是这个形状,只是生成模型一格都没有。
 *
 * **不做推断**。按模型名跨 vendor 猜是有害的:实测同一个 qwen-image-edit,alibaba 自家只收
 * 一张参考图、没有尺寸,经 evolink 则收 14 张还能选尺寸 —— 猜过去的参数会被端点当场拒掉。
 * 所以要么目录认得,要么用户在这里说。
 */
function CapabilityRefField({
  profileId,
  kind,
  showKind,
  value,
  known,
  onChange,
  onDescribe,
}: {
  profileId: string;
  kind: GenerationKind;
  /** 双能力模型两个字段同组,kind 缀在字段名后面区分;单 kind 时缀它是噪音。 */
  showKind?: boolean;
  value: string | null;
  known: boolean;
  onChange: (next: string | null) => void;
  /** 就地换体去写一份参数组。`null` = 新建,否则是要编辑的那一份。 */
  onDescribe: (profileRowId: string | null) => void;
}) {
  const t = useI18n();
  const refs = useQuery({
    queryKey: ["generation-capability-refs", profileId, kind],
    queryFn: () => api<CapabilityRefs>(`/api/generation/capability-refs?kind=${kind}&profile_id=${profileId}`),
    staleTime: 5 * 60_000,
  });
  const NONE = "__follow__";
  const fallbackKeys = refs.data?.fallback_keys ?? [];
  const data = refs.data;
  /* 「和 X 一样」排在前面,而且是**指针**:以后我们把 X 的描述符改宽了,指着它的行跟着变。
     档案排在后面,它是目录里没有对应模型时的出路(某个中转独有的组合)。
     两边都把参数列出来 —— 选之前就该看得见"选它会得到哪几项",而不是选完回去翻界面。 */
  const options = [
    { value: NONE, label: t("modelGenerationRefFollow"), description: t("modelGenerationRefFollowHint") },
    ...(data?.models ?? []).map((one) => ({
      value: one.value,
      label: `${one.model} · ${one.provider}`,
      description: one.parameter_keys.join(" · ") || t("modelGenerationRefNoParams"),
      keywords: [one.provider, one.model],
    })),
    ...(data?.profiles ?? []).map((one) => ({
      value: one.value,
      label: t("modelGenerationRefProfile").replace("{name}", one.profile),
      description: one.parameter_keys.join(" · ") || t("modelGenerationRefNoParams"),
      keywords: [one.profile],
    })),
  ];
  //: 当前选中的是不是我自己建的那种 —— 是的话给一个就地编辑的入口(改名、调字段、删除)。
  const editableProfile = (data?.profiles ?? []).find((one) => one.value === value && one.custom);

  return (
    <div className="grid gap-2">
      <label className="grid gap-1 text-ui-sm font-medium text-foreground">
        <span className="flex items-center gap-1.5">
          {t("modelGenerationRef")}
          {showKind && (
            <span className="rounded bg-secondary px-1 py-px text-ui-2xs font-normal text-muted-foreground">{kind}</span>
          )}
        </span>
      <OptionPicker
        ariaLabel={t("modelGenerationRef")}
        value={value ?? NONE}
        onChange={(next) => onChange(next === NONE ? null : next)}
        options={options}
        contentClassName="max-w-[min(520px,calc(100vw-32px))]"
      />
      </label>
      {/* 写一份 / 改一份都在字段**下面**,不在选择器里面。选择器里该只有能选的**值**
          (自动识别、和某个模型一样、某个参数组);「自己描述这个端点」是一个动作 ——
          混进去之后,它既像一个可以选中的取值,又要在选中的瞬间把整个对话框换掉。
          管理入口仍然只从**用它的那个模型**进入:参数组本来就是为某个模型建的,
          单开一页的结果是那一页永远空着,而入口还挡在路上。 */}
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
        <button
          type="button"
          className="cursor-pointer text-ui-xs text-muted-foreground underline-offset-2 hover:text-foreground hover:underline"
          onClick={() => onDescribe(null)}
        >
          {t("modelGenerationRefDescribe")}
        </button>
        {editableProfile && (
          <button
            type="button"
            className="cursor-pointer text-ui-xs text-muted-foreground underline-offset-2 hover:text-foreground hover:underline"
            onClick={() => onDescribe(editableProfile.id ?? null)}
          >
            {t("modelGenerationRefEditThis")}
          </button>
        )}
      </div>
      {/* 落到兜底时要出声。静默地什么都不显示,正是让人以为"这个模型就是没参数"的那种沉默。
          **但处境有两种。** 这条通道不按模型名分支时,我们说得出它发得出哪几项(请求是自己
          构造的);给不出时才是真的只剩提示词。说清前者能帮用户判断该指哪个参照模型。
          注意这里说的是"通道发得出",不是"生成界面会摆出来" —— 界面在没有可选值时会凭空
          造出整张清单(size→1024x1024、duration→5),所以那些键要等界面能表达"不知道有哪些
          取值"之后才放出来。见 domain/generation/catalog.fallback_capabilities。 */}
      {!known && !value && (
        <p className="m-0 text-ui-xs leading-[1.45] text-warning">
          {fallbackKeys.length > 0
            ? t("modelGenerationRefUnverified").replace("{keys}", fallbackKeys.join(" · "))
            : t("modelGenerationRefUnknown")}
        </p>
      )}
    </div>
  );
}

export function ModelSettingsDialog({
  profileId,
  modelId,
  vendor,
  open,
  onOpenChange,
}: {
  profileId: string;
  modelId: string;
  /** 决定可选能力范围(这个 vendor 的预设)。 */
  vendor?: string;
  open: boolean;
  onOpenChange: (next: boolean) => void;
}) {
  const t = useI18n();
  const formId = React.useId();
  const qc = useQueryClient();
  /* **就地换体,不叠弹窗。** 写一份参数组曾经是"链接 → 库弹窗 → 编辑器弹窗",三层叠着,
     而且建完还得回到选择器再选一次。现在它换掉这个对话框的主体,保存后回来、且已选中。 */
  const [describing, setDescribing] = React.useState<{ kind: GenerationKind; rowId: string | null } | null>(null);
  const [draft, setDraft] = React.useState<ModelSettingsDraft | null>(null);
  const [advancedOpen, setAdvancedOpen] = React.useState(false);
  const capabilityOptions = useCapabilityOptions(vendor);

  // 从合并后的模型列表里取这一行 —— 目录与覆盖的合并逻辑只该有一处,再开一个单独的读接口
  // 就会出现"列表说 128k、弹窗说 32k"这种两份真相。
  const settings = useQuery({
    queryKey: ["provider-models", profileId],
    queryFn: () => api<ModelSettings[]>(`/api/settings/providers/${profileId}/models`),
    enabled: open,
    select: (rows) => rows.find((row) => row.id === modelId) ?? null,
  });

  React.useEffect(() => {
    if (settings.data) setDraft(settings.data);
  }, [settings.data]);

  const save = useMutation({
    mutationFn: (body: Record<string, unknown>) =>
      api<ModelSettings>(`/api/settings/providers/${profileId}/models/${encodeURIComponent(modelId)}`, {
        method: "PATCH",
        body: JSON.stringify(body),
      }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["provider-models", profileId] });
      void qc.invalidateQueries({ queryKey: ["provider-defaults"] });
      void qc.invalidateQueries({ queryKey: ["capability-models"] });
      onOpenChange(false);
    },
  });

  const current = draft ?? settings.data ?? null;
  const source = settings.data?.context_window_source ?? "fallback";
  const outputSource = settings.data?.max_output_tokens_source ?? "fallback";
  //: 查到的**上限**(目录报的,或内置查证表里的)。和下面的 effective 是两回事。
  //: 查证过的结论(True/False/未查证)。和用户填的那一格是两回事。
  const knownStructured = settings.data?.known_structured_output ?? null;
  const knownWindow = settings.data?.context_window ?? 0;
  const knownOutput = settings.data?.max_output_tokens ?? 0;
  //: 不是用户自己填的那份上限。输入框里的值和它相等时保存成 null —— 把继承来的值钉死,
  //: 供应商哪天调了上限就跟不上了,而用户以为自己什么都没改。
  const inherited = source === "override" ? null : (settings.data?.context_window ?? null);
  const inheritedOutput = outputSource === "override" ? null : (settings.data?.max_output_tokens ?? null);
  //: 清空输入框时实际会发出去的那两个数,**由后端给**,不在这里再算一份。此前这里写死
  //: 32000,而远程端点运行时用的是 128000 —— 界面告诉用户的数和请求真正带的数不是一个,
  //: 于是「为什么只有这么点输出额度」从界面上根本推不出来。
  const effectiveWindow = settings.data?.effective_context_window ?? 0;
  const effectiveOutput = settings.data?.effective_max_output_tokens ?? 0;
  //: 上限比默认预算高时,这两个数会不一样(DeepSeek 上限 384,000,默认按 65,536 发)。
  //: 只在不一样时多说一句 —— 相等时那句话是废话。
  const outputCapped = outputSource !== "override" && knownOutput > 0 && effectiveOutput < knownOutput;
  // 上下文窗口与那几个兼容开关只对**对话**模型有意义 —— 给一个生图模型显示"支持 developer 角色"
  // 纯属噪音,还会让人以为漏配了什么。
  //
  // 按**草稿**算而不是服务端回的 effective:用户刚把 chat 取消掉,下面那些项就该立刻消失,
  // 而不是等保存并重新拉一次才反应过来。自己填了能力就以它为准,没填才跟随预设。
  const own = current?.capability_ids ?? [];
  const effective = own.length > 0 ? own : (current?.effective_capability_ids ?? []);
  const isChat = effective.includes("chat");
  //: 生成模型才谈得上"生成参数按什么来"。图片和视频各有一套描述符,所以要分别问。
  const generationKinds = GENERATION_KINDS.filter((kind) => effective.includes(kind));

  return (
    describing ? (
      /* **同一个对话框,换掉主体。** 不叠第二层:叠上去的那一层会把"我正在配这个模型"这件事
         推到背景里,而用户做的自始至终是同一件事。返回箭头回到模型设置,保存后新建的那份
         已经选中 —— 创建这一步本身就把任务做完了。 */
      <ProfileBody
        profileId={profileId}
        kind={describing.kind}
        rowId={describing.rowId}
        onBack={() => setDescribing(null)}
        onSaved={(ref) => {
          setDraft((prev) => (prev ? {
            ...prev,
            generation_capability_refs: { ...(prev.generation_capability_refs ?? {}), [describing.kind]: ref },
          } : prev));
          void qc.invalidateQueries({ queryKey: ["generation-capability-refs", profileId, describing.kind] });
          setDescribing(null);
        }}
        open={open}
        onOpenChange={onOpenChange}
      />
    ) : (
    <ModalShell
      open={open}
      onOpenChange={onOpenChange}
      title={t("modelSettingsTitle")}
      footer={
        <>
          <Button type="button" variant="outline" size="sm" onClick={() => onOpenChange(false)}>{t("cancel")}</Button>
          <Button type="submit" form={formId} size="sm" disabled={!current} loading={save.isPending}>{t("save")}</Button>
        </>
      }
    >
      <form
        id={formId}
        className="grid gap-3"
        onSubmit={(event) => {
          event.preventDefault();
          if (!current) return;
          save.mutate({
            capability_ids: current.capability_ids ?? [],
            context_window: source === "override" || current.context_window !== inherited ? current.context_window : null,
            max_output_tokens:
              outputSource === "override" || current.max_output_tokens !== inheritedOutput
                ? current.max_output_tokens
                : null,
            reasoning: current.reasoning,
            vision: current.vision,
            reasoning_effort: current.reasoning_effort,
            developer_role: current.developer_role,
            structured_output: current.structured_output,
            generation_capability_refs: current.generation_capability_refs ?? {},
          });
        }}
      >
        {/* 模型 id 单独一行:它常常很长(doubao-seedream-4-0-250828),挤进标题会把整行顶掉。 */}
        <p className="m-0 truncate font-mono text-ui-sm text-muted-foreground" title={modelId}>
          {modelId}
        </p>

        <div className="grid gap-1.5">
          <span className="text-ui-md font-medium text-foreground">{t("modelCapabilities")}</span>
          {/* 能力放在最前:它决定下面显示什么 —— 生图模型没有上下文窗口,也不认 developer 角色。
              留空表示跟随 vendor 预设。这句话说的就是这件事:少了它,读者只能从"点掉 chat
              之后下面少了一半"倒着猜这一组管什么。 */}
          <p className="m-0 text-xs leading-[1.45] text-muted-foreground">{t("modelCapabilitiesHint")}</p>
          <div className="flex flex-wrap gap-1.5">
            {capabilityOptions.map((capability) => {
              // **按生效值高亮**,而不是只按显式设置。列表行上的标签画的就是生效值 ——
              // 行里明明标着 image/video,点开却一个都不亮,读起来像丢了配置。
              // 继承来的用浅底区分:亮着,但看得出"这是跟着预设来的"。
              const explicit = (current?.capability_ids ?? []).includes(capability);
              const inherited = own.length === 0 && effective.includes(capability);
              return (
                <button
                  key={capability}
                  type="button"
                  className={cn(
                    "cursor-pointer rounded-full border px-2.5 py-1 text-ui-xs transition-colors",
                    explicit && "border-primary bg-action text-action-foreground",
                    inherited && "border-primary/50 bg-[color-mix(in_srgb,var(--primary)_14%,transparent)] text-foreground",
                    !explicit && !inherited && "border-border bg-panel text-muted-foreground hover:border-border-strong",
                  )}
                  onClick={() =>
                    setDraft((prev) => {
                      if (!prev) return prev;
                      // 从"跟随预设"里点掉一项时,先把继承的那份落成显式的,再去掉这一项 ——
                      // 否则第一次点击会把整组清空,表现成"点一下全没了"。
                      const base = (prev.capability_ids ?? []).length > 0 ? prev.capability_ids ?? [] : effective;
                      const has = base.includes(capability);
                      return {
                        ...prev,
                        capability_ids: has ? base.filter((item) => item !== capability) : [...base, capability],
                      };
                    })
                  }
                >
                  {capability}
                </button>
              );
            })}
          </div>
          {own.length === 0 ? (
            <span className="text-xs leading-[1.45] text-muted-foreground">
              {t("modelCapabilitiesInherit").replace("{list}", effective.join(" / "))}
            </span>
          ) : (
            <button
              type="button"
              className="justify-self-start cursor-pointer border-0 bg-transparent p-0 text-xs text-muted-foreground underline-offset-2 hover:text-foreground hover:underline"
              onClick={() => setDraft((prev) => (prev ? { ...prev, capability_ids: [] } : prev))}
            >
              {t("modelCapabilitiesFollowPreset")}
            </button>
          )}
        </div>

        {isChat && (
          /* 对话那一组。**整组由能力决定出不出现** —— 和下面生成那组对称,两组同一个规格:
             一条分隔线起头、一个组标题、组内才是各项。此前上下文、高级、生成参数三块平级摆着,
             同样的标题字号,读者得自己在脑子里分组。 */
          <div className="grid gap-2 border-t border-border pt-3">
            <span className="text-ui-md font-medium text-foreground">{t("modelSettingsChatGroup")}</span>
            <div className="grid gap-1">
              <label className="text-ui-sm font-medium text-foreground" htmlFor="ctx">
                {t("modelSettingsContextWindow")}
              </label>
              <Input
                id="ctx"
                type="number"
                min={1024}
                // 与下面的高级卡片同一个底色。Input 默认的 bg-field 是米色填充,而弹窗表面
                // 本身已经带底色 —— 填充色叠在上面会读成"这个框是禁用的",旁边又是白卡片,
                // 对比之下更明显。
                className="bg-panel"
                value={current?.context_window ?? ""}
                placeholder={String(effectiveWindow)}
                onChange={(event) =>
                  setDraft((prev) =>
                    prev ? { ...prev, context_window: event.target.value ? Number(event.target.value) : null } : prev,
                  )
                }
              />
            </div>
            <p className="m-0 text-xs leading-[1.45] text-muted-foreground">
              {source === "override"
                ? t("modelSettingsSourceOverride")
                : source === "catalog"
                  ? t("modelSettingsSourceCatalog").replace("{n}", String(knownWindow))
                  : source === "builtin"
                    ? t("modelSettingsSourceBuiltin").replace("{n}", String(knownWindow))
                    : t("modelSettingsSourceFallback").replace("{n}", String(effectiveWindow))}
            </p>
            <p className="m-0 text-xs leading-[1.45] text-muted-foreground">{t("modelSettingsContextWindowHint")}</p>

            {/* 输出额度。**和上下文是两件事**:上面那个是"能聊多久",这个是"一次能说多长" ——
                而思考 token 也花在这一份额度里,不够时模型会把它全花在思考上,一个字都没说出来
                就被截断(用户看到的是「已用完本轮输出额度」,而此前界面上根本没有这一项可调)。 */}
            <div className="grid gap-1">
              <label className="text-ui-sm font-medium text-foreground" htmlFor="max-output">
                {t("modelSettingsMaxOutput")}
              </label>
              <Input
                id="max-output"
                type="number"
                min={256}
                className="bg-panel"
                value={current?.max_output_tokens ?? ""}
                placeholder={String(effectiveOutput)}
                onChange={(event) =>
                  setDraft((prev) =>
                    prev
                      ? { ...prev, max_output_tokens: event.target.value ? Number(event.target.value) : null }
                      : prev,
                  )
                }
              />
            </div>
            <p className="m-0 text-xs leading-[1.45] text-muted-foreground">
              {outputSource === "override"
                ? t("modelSettingsOutputSourceOverride")
                : outputSource === "catalog"
                  ? t("modelSettingsOutputSourceCatalog").replace("{n}", String(knownOutput))
                  : outputSource === "builtin"
                    ? t("modelSettingsOutputSourceBuiltin").replace("{n}", String(knownOutput))
                    : t("modelSettingsOutputSourceFallback").replace("{n}", String(effectiveOutput))}
            </p>
            {outputCapped && (
              <p className="m-0 text-xs leading-[1.45] text-muted-foreground">
                {t("modelSettingsOutputCapped").replace("{n}", String(effectiveOutput))}
              </p>
            )}
            <p className="m-0 text-xs leading-[1.45] text-muted-foreground">{t("modelSettingsMaxOutputHint")}</p>
          </div>
        )}

        {isChat && (
          /* 高级是**对话那一组里**的折叠开关,不是又一个区段 —— 它此前顶着同样的标题字号、
             上面还有自己的分隔线,于是读起来像第三个并列的标题。 */
          <div className="-mt-1">
            <button
              type="button"
              className="flex w-full cursor-pointer items-center justify-between gap-2 border-0 bg-transparent p-0 text-left"
              onClick={() => setAdvancedOpen((v) => !v)}
            >
              <span className="text-ui-sm font-medium text-muted-foreground">{t("modelSettingsAdvanced")}</span>
              <span className="flex items-center gap-1 text-ui-xs text-muted-foreground">
                {t("modelSettingsAdvancedHint")}
                <ChevronDown size={13} className={cn("transition-transform", advancedOpen && "rotate-180")} />
              </span>
            </button>
            {advancedOpen && current && (
              <div className="mt-1.5 grid gap-1.5">
                <AdvancedToggle
                  label={t("modelSettingsReasoning")}
                  hint={t("modelSettingsReasoningHint")}
                  value={current.reasoning}
                  onChange={(next) => setDraft((prev) => (prev ? { ...prev, reasoning: next } : prev))}
                />
                {/* 「推理模型」是**开关总闸**,而档位发不发得出去是另一件事(见后端
                    domain/thinking)。两者此前只有前者露在界面上,于是"开着却没有档位"
                    读起来像配漏了 —— 而它恰恰是我们主动不给的。 */}
                <p className="m-0 pl-0.5 text-xs leading-[1.45] text-muted-foreground">
                  {(settings.data?.thinking_levels ?? []).length > 0
                    ? t("modelSettingsThinkingLevels").replace(
                        "{list}",
                        (settings.data?.thinking_levels ?? []).join(" / "),
                      )
                    : t("modelSettingsThinkingLevelsNone")}
                </p>
                <AdvancedToggle
                  label={t("modelSettingsVision")}
                  hint={t("modelSettingsVisionHint")}
                  value={current.vision}
                  onChange={(next) => setDraft((prev) => (prev ? { ...prev, vision: next } : prev))}
                />
                <AdvancedToggle
                  label={t("modelSettingsReasoningEffort")}
                  hint={t("modelSettingsReasoningEffortHint")}
                  value={current.reasoning_effort}
                  onChange={(next) => setDraft((prev) => (prev ? { ...prev, reasoning_effort: next } : prev))}
                />
                <AdvancedToggle
                  label={t("modelSettingsDeveloperRole")}
                  hint={t("modelSettingsDeveloperRoleHint")}
                  value={current.developer_role}
                  onChange={(next) => setDraft((prev) => (prev ? { ...prev, developer_role: next } : prev))}
                />
                <AdvancedToggle
                  label={t("modelSettingsStructuredOutput")}
                  hint={t("modelSettingsStructuredOutputHint")}
                  value={current.structured_output}
                  onChange={(next) => setDraft((prev) => (prev ? { ...prev, structured_output: next } : prev))}
                />
                {/* **「我们知道什么」和「你填了什么」分开说。** 不支持 json_schema 的端点上,
                    Schema 只是个事后本地校验 —— 而用户在节点里写着 strict,完全看不出来。
                    两次真实失败都是这么来的(字段超范围、整份 JSON 没闭合)。 */}
                <p className="m-0 pl-0.5 text-xs leading-[1.45] text-muted-foreground">
                  {knownStructured === true
                    ? t("modelSettingsStructuredOutputKnownOn")
                    : knownStructured === false
                      ? t("modelSettingsStructuredOutputKnownOff")
                      : t("modelSettingsStructuredOutputUnknown")}
                </p>
              </div>
            )}
          </div>
        )}

        {/* 「生成」组头只说一遍:双能力模型的两个 kind 共享这一组,kind 落在字段名后面,
            而不是把整组(标题、分隔线、间距)原样再来一遍。 */}
        {current && generationKinds.length > 0 && (
          <div className="grid gap-3 border-t border-border pt-3">
            <span className="text-ui-md font-medium text-foreground">{t("modelSettingsGenerationGroup")}</span>
            {generationKinds.map((kind) => (
              <CapabilityRefField
                key={kind}
                profileId={profileId}
                kind={kind}
                showKind={generationKinds.length > 1}
                value={current.generation_capability_refs?.[kind] ?? null}
                known={current.generation_capabilities_known_by_kind?.[kind] !== false}
                onDescribe={(rowId) => setDescribing({ kind, rowId })}
                onChange={(next) => setDraft((prev) => (prev ? {
                  ...prev,
                  generation_capability_refs: {
                    ...(prev.generation_capability_refs ?? {}),
                    [kind]: next,
                  },
                } : prev))}
              />
            ))}
          </div>
        )}

      </form>
    </ModalShell>
    )
  );
}

/**
 * 写一份参数组 —— **和模型设置共用同一个对话框**,不是叠上去的第二层。
 *
 * 此前这里是「管理参数组」链接 → 一层库弹窗(空列表时全部内容是一句话加一个按钮)→ 一层
 * 编辑器弹窗,而且建完还得回到选择器再选一次:六步三个界面,而创建那一步本身没有完成任务。
 *
 * 现在它是选择器里的一个分支。返回回到模型设置;保存后**新建的那份已经选中**。
 * 改名 / 调字段 / 删除也都在这里 —— 独立的"管理列表"删掉了,参数组本来就是为某个模型建的。
 */
function ProfileBody({
  profileId,
  kind,
  rowId,
  open,
  onOpenChange,
  onBack,
  onSaved,
}: {
  profileId: string;
  kind: GenerationKind;
  /** null = 新建。 */
  rowId: string | null;
  open: boolean;
  onOpenChange: (next: boolean) => void;
  onBack: () => void;
  onSaved: (ref: string) => void;
}) {
  const t = useI18n();
  const qc = useQueryClient();
  /* 从**列表**里取那一份,不新开一个"取单份"的接口:这条连接下的参数组本来就是个短清单,
     列表那次请求多半已经在缓存里 —— 为一份数据再加一条路由是给自己多留一处会走岔的口径。 */
  const existing = useQuery({
    queryKey: ["generation-profiles", profileId, kind],
    queryFn: () => api<{ id: string; name: string; capabilities: Record<string, unknown> }[]>(
      `/api/settings/providers/${profileId}/generation-profiles?kind=${kind}`,
    ),
    enabled: Boolean(rowId),
  });
  const row = rowId ? existing.data?.find((one) => one.id === rowId) : undefined;
  const [name, setName] = React.useState("");
  const [descriptor, setDescriptor] = React.useState<Record<string, unknown>>({});
  const [error, setError] = React.useState("");
  const loaded = React.useRef(false);
  React.useEffect(() => {
    if (rowId && row && !loaded.current) {
      loaded.current = true;
      setName(row.name);
      setDescriptor({ ...row.capabilities });
    }
  }, [rowId, row]);

  const save = useMutation({
    mutationFn: (body: Record<string, unknown>) =>
      rowId
        ? api<{ id: string }>(`/api/settings/providers/${profileId}/generation-profiles/${rowId}`, {
            method: "PATCH", body: JSON.stringify(body),
          })
        : api<{ id: string }>(`/api/settings/providers/${profileId}/generation-profiles`, {
            method: "POST", body: JSON.stringify({ ...body, kind }),
          }),
    onSuccess: (row) => onSaved(`profile:${row.id}`),
    //: 后端的报错已经点名了是哪个键,原样显示,别包一层"保存失败"。
    onError: (err: Error) => setError(err.message),
  });
  const remove = useMutation({
    mutationFn: () => api<void>(`/api/settings/providers/${profileId}/generation-profiles/${rowId}`, { method: "DELETE" }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["generation-capability-refs", profileId, kind] });
      onBack();
    },
    onError: (err: Error) => setError(err.message),
  });

  return (
    <ModalShell
      open={open}
      onOpenChange={onOpenChange}
      title={
        <span className="flex min-w-0 items-center gap-1.5">
          {/* 返回,不是关闭 —— 关掉会把用户正在配的那个模型一起丢了。 */}
          <button
            type="button"
            aria-label={t("back")}
            className="-ml-1 grid size-6 shrink-0 cursor-pointer place-items-center rounded-md text-muted-foreground transition-colors hover:bg-secondary hover:text-foreground"
            onClick={onBack}
          >
            <ChevronLeft size={15} />
          </button>
          <span className="truncate">{rowId ? t("modelGenerationRefEditThis") : t("modelGenerationRefDescribeTitle")}</span>
          <span className="rounded bg-secondary px-1 py-px text-ui-2xs font-normal text-muted-foreground">{kind}</span>
        </span>
      }
      footer={
        <>
          {/* 删除只在编辑已有的那一份时出现,而且靠左 —— 和"保存"分开站,别让人误点。 */}
          {rowId && (
            <Button
              type="button" variant="ghost" size="sm"
              className="mr-auto text-destructive hover:text-destructive"
              loading={remove.isPending}
              onClick={() => remove.mutate()}
            >
              {t("delete")}
            </Button>
          )}
          <Button type="button" variant="outline" size="sm" onClick={onBack}>{t("back")}</Button>
          <Button
            type="button" size="sm"
            disabled={!name.trim()}
            loading={save.isPending}
            onClick={() => save.mutate({ name: name.trim(), capabilities: descriptor })}
          >
            {t("save")}
          </Button>
        </>
      }
    >
      <div className="grid gap-3">
        {/* 名字这一格走表单里同一个外壳 —— 各写各的话,同一屏上就有两种标签字号、两种输入框高度。 */}
        <ProfileField label={t("generationProfilesName")}>
          <Input
            value={name}
            aria-label={t("generationProfilesName")}
            onChange={(event) => setName(event.target.value)}
            className="bg-panel"
          />
        </ProfileField>
        <CapabilityProfileForm kind={kind} value={descriptor} onChange={setDescriptor} />
        {error && <p className="m-0 text-ui-xs leading-[1.45] text-destructive">{error}</p>}
        <p className="m-0 text-ui-xs leading-[1.45] text-muted-foreground">{t("generationProfilesDisclaimer")}</p>
      </div>
    </ModalShell>
  );
}
