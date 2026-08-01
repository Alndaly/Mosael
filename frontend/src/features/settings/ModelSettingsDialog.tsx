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
import { SettingsRow } from "@/features/settings/ui";
import { cn } from "@/lib/utils";

type ModelSettings = components["schemas"]["ModelSettingsOut"];

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
  return (
    // 用设置页同一套 SettingsRow:标签+说明在左、控件在右,行距与分隔线都跟外面一致。
    // 自己手写一套的结果就是同一个应用里两种"开关行",间距和字号都对不上。
    <SettingsRow label={label} description={hint}>
      {/* 设过之后才给「跟随默认」——没设过时它本来就是跟随,常驻这个按钮只会让人以为漏了什么。 */}
      {value !== null && value !== undefined && (
        <button
          type="button"
          className="cursor-pointer border-0 bg-transparent p-0 text-[11px] text-muted-foreground underline-offset-2 hover:text-foreground hover:underline"
          onClick={() => onChange(null)}
        >
          {t("modelSettingsFollowDefault")}
        </button>
      )}
      <Switch checked={Boolean(value)} onCheckedChange={(next) => onChange(next)} />
    </SettingsRow>
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

  const settings = useQuery({
    queryKey: ["model-settings", profileId, modelId],
    queryFn: () => api<ModelSettings>(`/api/settings/providers/${profileId}/models/${encodeURIComponent(modelId)}/settings`),
    enabled: open,
  });

  React.useEffect(() => {
    if (settings.data) setDraft(settings.data);
  }, [settings.data]);

  const save = useMutation({
    mutationFn: (body: Record<string, unknown>) =>
      api<ModelSettings>(`/api/settings/providers/${profileId}/models/${encodeURIComponent(modelId)}/settings`, {
        method: "PUT",
        body: JSON.stringify(body),
      }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["model-settings", profileId, modelId] });
      onOpenChange(false);
    },
  });

  const current = draft ?? settings.data ?? null;
  const source = settings.data?.context_window_source ?? "fallback";
  // 目录给了就把它当占位提示:用户清空输入框时,回到的正是这个值。
  const inherited = source === "catalog" ? settings.data?.context_window : null;

  return (
    <ModalShell open={open} onOpenChange={onOpenChange} title={`${t("modelSettingsTitle")} · ${modelId}`}>
      <form
        className="grid gap-3"
        onSubmit={(event) => {
          event.preventDefault();
          if (!current) return;
          save.mutate({
            context_window: source === "override" || current.context_window !== inherited ? current.context_window : null,
            reasoning: current.reasoning,
            vision: current.vision,
            reasoning_effort: current.reasoning_effort,
            developer_role: current.developer_role,
          });
        }}
      >
        <div className="grid gap-1.5">
          <div className="grid gap-1">
            <label className="text-[13px] font-medium text-foreground" htmlFor="ctx">
              {t("modelSettingsContextWindow")}
            </label>
            <Input
              id="ctx"
              type="number"
              min={1024}
              value={current?.context_window ?? ""}
              placeholder={String(inherited ?? FALLBACK_CONTEXT_WINDOW)}
              onChange={(event) =>
                setDraft((prev) =>
                  prev ? { ...prev, context_window: event.target.value ? Number(event.target.value) : null } : prev,
                )
              }
            />
          </div>
          {/* 说清这个数从哪来:只给一个输入框的话,用户不知道现在的 32000 是端点说的还是我们兜的底,
              也不知道清空之后会变成什么。 */}
          <p className="m-0 text-xs leading-[1.45] text-muted-foreground">
            {source === "override"
              ? t("modelSettingsSourceOverride")
              : source === "catalog"
                ? t("modelSettingsSourceCatalog").replace("{n}", String(inherited ?? 0))
                : t("modelSettingsSourceFallback").replace("{n}", String(FALLBACK_CONTEXT_WINDOW))}
          </p>
        </div>

        <div className="overflow-hidden rounded-lg border border-border">
          <button
            type="button"
            className="flex w-full cursor-pointer items-center justify-between gap-3 border-0 bg-transparent px-3.5 py-3 text-left"
            onClick={() => setAdvancedOpen((v) => !v)}
          >
            <span className="grid gap-0.5">
              <span className="text-[13px] font-medium text-foreground">{t("modelSettingsAdvanced")}</span>
              <small className="text-xs leading-[1.45] text-muted-foreground">{t("modelSettingsAdvancedHint")}</small>
            </span>
            <ChevronDown
              size={14}
              className={cn("shrink-0 text-muted-foreground transition-transform", advancedOpen && "rotate-180")}
            />
          </button>
          {advancedOpen && current && (
            // 分隔线由这一层统一给,和 SettingsGroup 的做法一致 —— 每行自己带边框会在折叠处多出一条。
            <div className="border-t border-border [&>*+*]:border-t [&>*+*]:border-border">
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
