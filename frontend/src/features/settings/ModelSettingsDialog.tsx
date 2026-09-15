import React from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ChevronDown } from "lucide-react";

import { api } from "@/api/client";
import type { components } from "@/api/generated/schema";
import { useI18n } from "@/app/preferences";
import { ModalShell } from "@/components/app/modals";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { OptionPicker } from "@/components/ui/option-picker";
import { Switch } from "@/components/ui/switch";
import { cn } from "@/lib/utils";

import { GenerationProfilesDialog } from "./GenerationProfilesSection";

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

/** 端点和目录都没给时,sidecar 用的保守回退。界面上要显示出来 —— 否则"空着"会被读成"不限"。 */
const FALLBACK_CONTEXT_WINDOW = 32000;

type VendorPreset = components["schemas"]["VendorPresetOut"];

/**
 * 可选能力**由后端的 vendor 预设给**,不在这里手抄一份。
 *
 * 抄一份的代价刚兑现过:这里曾照着 `provider_defaults.CAPABILITIES` 写死五项,而模型行认的是
 * `providers.ALL_CAPABILITY_IDS` 六项 —— 于是 embedding 在列表行上有标签、在弹窗里却根本没有
 * 对应的格子,既看不到也改不了。
 *
 * 用**这个 vendor 的**预设而不是全集,还顺带解决了另一半:给 ComfyUI 工作流列 chat/tts、
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
  profiles: { value: string; profile: string; parameter_keys: string[] }[];
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
}: {
  profileId: string;
  kind: "image" | "video";
  /** 双能力模型两个字段同组,kind 缀在字段名后面区分;单 kind 时缀它是噪音。 */
  showKind?: boolean;
  value: string | null;
  known: boolean;
  onChange: (next: string | null) => void;
}) {
  const t = useI18n();
  const qc = useQueryClient();
  const refs = useQuery({
    queryKey: ["generation-capability-refs", profileId, kind],
    queryFn: () => api<CapabilityRefs>(`/api/generation/capability-refs?kind=${kind}&profile_id=${profileId}`),
    staleTime: 5 * 60_000,
  });
  const NONE = "__follow__";
  /* 管理的入口就在绑定的地方:挑参数来源时才发现"目录没有、参数组也没有"的人,
     不该再回设置页翻一节 —— 就在这里开门。 */
  const MANAGE = "__manage__";
  const [managing, setManaging] = React.useState(false);
  const data = refs.data;
  /* 「和 X 一样」排在前面,而且是**指针**:以后我们把 X 的描述符改宽了,指着它的行跟着变。
     档案排在后面,它是目录里没有对应模型时的出路(某个中转独有的组合)。
     两边都把参数列出来 —— 选之前就该看得见"选它会得到哪几项",而不是选完回去翻界面。 */
  const options = [
    { value: NONE, label: t("modelGenerationRefFollow") },
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
    { value: MANAGE, label: t("generationProfilesManage") },
  ];

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
        onChange={(next) => {
          if (next === MANAGE) {
            setManaging(true);
            return;
          }
          onChange(next === NONE ? null : next);
        }}
        options={options}
        contentClassName="max-w-[min(520px,calc(100vw-32px))]"
      />
      </label>
      {/* 落到兜底时要出声。静默地什么都不显示,正是让人以为"这个模型就是没参数"的那种沉默。 */}
      {!known && !value && (
        <p className="m-0 text-ui-xs leading-[1.45] text-warning">{t("modelGenerationRefUnknown")}</p>
      )}
      {managing && (
        <GenerationProfilesDialog
          profileId={profileId}
          kind={kind}
          open
          onOpenChange={(next) => {
            setManaging(next);
            /* 建完/删完,选择器里的清单要跟着变 —— 刚建好的那份要能马上选到。 */
            if (!next) void qc.invalidateQueries({ queryKey: ["generation-capability-refs", profileId, kind] });
          }}
        />
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
  /** 决定标题措辞与可选能力范围。ComfyUI 这里管的是工作流,不是模型。 */
  vendor?: string;
  open: boolean;
  onOpenChange: (next: boolean) => void;
}) {
  const t = useI18n();
  const formId = React.useId();
  const qc = useQueryClient();
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
  // 目录给了就把它当占位提示:用户清空输入框时,回到的正是这个值。
  const inherited = source === "catalog" ? settings.data?.context_window : null;
  // 上下文窗口与那几个兼容开关只对**对话**模型有意义 —— 给一个生图模型显示"支持 developer 角色"
  // 纯属噪音,还会让人以为漏配了什么。
  //
  // 按**草稿**算而不是服务端回的 effective:用户刚把 chat 取消掉,下面那些项就该立刻消失,
  // 而不是等保存并重新拉一次才反应过来。自己填了能力就以它为准,没填才跟随预设。
  const own = current?.capability_ids ?? [];
  const effective = own.length > 0 ? own : (current?.effective_capability_ids ?? []);
  const isChat = effective.includes("chat");
  //: 生成模型才谈得上"生成参数按什么来"。图片和视频各有一套描述符,所以要分别问。
  const generationKinds = (["image", "video"] as const).filter((kind) => effective.includes(kind));

  return (
    <ModalShell
      open={open}
      onOpenChange={onOpenChange}
      title={vendor === "comfyui" ? t("workflowSettingsTitle") : t("modelSettingsTitle")}
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
            reasoning: current.reasoning,
            vision: current.vision,
            reasoning_effort: current.reasoning_effort,
            developer_role: current.developer_role,
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
              留空表示跟随 vendor 预设。 */}
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
                placeholder={String(inherited ?? FALLBACK_CONTEXT_WINDOW)}
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
                  ? t("modelSettingsSourceCatalog").replace("{n}", String(inherited ?? 0))
                  : t("modelSettingsSourceFallback").replace("{n}", String(FALLBACK_CONTEXT_WINDOW))}
            </p>
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
  );
}
