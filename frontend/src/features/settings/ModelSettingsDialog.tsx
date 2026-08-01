import React from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ChevronDown } from "lucide-react";

import { api } from "@/api/client";
import type { components } from "@/api/generated/schema";
import { useI18n } from "@/app/preferences";
import { ModalShell } from "@/components/app/modals";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Switch } from "@/components/ui/switch";
import { cn } from "@/lib/utils";

type ModelSettings = components["schemas"]["ProviderModelOut"];

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

/** 可选能力。与后端 provider_defaults.CAPABILITIES 一致。 */
const CAPABILITIES = ["chat", "image", "video", "tts", "podcast"] as const;

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
        <span className="flex items-center gap-1.5 text-[12.5px] font-medium text-foreground">
          {label}
          {/* 设过之后才给「跟随默认」——没设过时它本来就是跟随,常驻只会让人以为漏了什么。 */}
          {set && (
            <button
              type="button"
              className="cursor-pointer border-0 bg-transparent p-0 text-[10.5px] font-normal text-muted-foreground underline-offset-2 hover:text-foreground hover:underline"
              onClick={() => onChange(null)}
            >
              {t("modelSettingsFollowDefault")}
            </button>
          )}
        </span>
        <span className="text-[11px] leading-[1.45] text-muted-foreground">{hint}</span>
      </div>
      <Switch className="shrink-0" checked={Boolean(value)} onCheckedChange={(next) => onChange(next)} />
    </div>
  );
}

export function ModelSettingsDialog({
  profileId,
  modelId,
  open,
  onOpenChange,
}: {
  profileId: string;
  modelId: string;
  open: boolean;
  onOpenChange: (next: boolean) => void;
}) {
  const t = useI18n();
  const qc = useQueryClient();
  const [draft, setDraft] = React.useState<ModelSettings | null>(null);
  const [advancedOpen, setAdvancedOpen] = React.useState(false);

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

  return (
    <ModalShell open={open} onOpenChange={onOpenChange} title={t("modelSettingsTitle")}>
      <form
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
          });
        }}
      >
        {/* 模型 id 单独一行:它常常很长(doubao-seedream-4-0-250828),挤进标题会把整行顶掉。 */}
        <p className="m-0 truncate font-mono text-[12px] text-muted-foreground" title={modelId}>
          {modelId}
        </p>

        <div className="grid gap-1.5">
          <span className="text-[13px] font-medium text-foreground">{t("modelCapabilities")}</span>
          {/* 能力放在最前:它决定下面显示什么 —— 生图模型没有上下文窗口,也不认 developer 角色。
              留空表示跟随 vendor 预设。 */}
          <div className="flex flex-wrap gap-1.5">
            {CAPABILITIES.map((capability) => {
              const active = (current?.capability_ids ?? []).includes(capability);
              return (
                <button
                  key={capability}
                  type="button"
                  className={cn(
                    "cursor-pointer rounded-full border px-2.5 py-1 text-[11.5px] transition-colors",
                    active
                      ? "border-primary bg-primary text-primary-foreground"
                      : "border-border bg-panel text-muted-foreground hover:border-border-strong",
                  )}
                  onClick={() =>
                    setDraft((prev) => {
                      if (!prev) return prev;
                      const own = prev.capability_ids ?? [];
                      return {
                        ...prev,
                        capability_ids: active ? own.filter((item) => item !== capability) : [...own, capability],
                      };
                    })
                  }
                >
                  {capability}
                </button>
              );
            })}
          </div>
          {(current?.capability_ids ?? []).length === 0 && (
            <span className="text-xs leading-[1.45] text-muted-foreground">
              {t("modelCapabilitiesInherit").replace("{list}", (current?.effective_capability_ids ?? []).join(" / "))}
            </span>
          )}
        </div>

        {isChat && (
          <div className="grid gap-1.5">
            <div className="grid gap-1">
              <label className="text-[13px] font-medium text-foreground" htmlFor="ctx">
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
          <div className="border-t border-border pt-2">
            {/* 弹窗本身已经有一圈边框,再套一个盒子就是框中框。一条分隔线足够划分区域。 */}
            <button
              type="button"
              className="flex w-full cursor-pointer items-center justify-between gap-2 border-0 bg-transparent p-0 text-left"
              onClick={() => setAdvancedOpen((v) => !v)}
            >
              <span className="text-[12.5px] font-medium text-foreground">{t("modelSettingsAdvanced")}</span>
              <span className="flex items-center gap-1 text-[11px] text-muted-foreground">
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

        <div className="flex justify-end gap-1.5">
          <Button type="button" variant="ghost" size="sm" onClick={() => onOpenChange(false)}>
            {t("cancel")}
          </Button>
          <Button type="submit" size="sm" disabled={save.isPending || !current}>
            {t("save")}
          </Button>
        </div>
      </form>
    </ModalShell>
  );
}
