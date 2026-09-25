import React from "react";
import { useQuery } from "@tanstack/react-query";
import { ChevronRight, RefreshCcw } from "lucide-react";

import {
  listPluginInstanceModels,
  type PluginCapabilityStatus,
  type PluginInstance,
  type PluginProvidedModel,
} from "@/api/client";
import type { MessageKey } from "@/app/messages";
import { useI18n, usePreferences } from "@/app/preferences";
import { ModalShell } from "@/components/app/modals";
import { SettingsRow } from "@/components/settings/settings-layout";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { ROLE_COPY, type SourceRole } from "@/features/ai-studio/sourceFrames";
import { relativeTime } from "@/lib/time";
import { cn } from "@/lib/utils";

/**
 * 替宿主做生成的插件(ComfyUI 这类)**提供了哪些模型**。任何一个声明了 `provides: ["generation"]` 的
 * 插件都走这里,不认识哪一家。
 *
 * 此前这一行只说「生成模型 · 2 个模型」,两个是什么、收什么、能调什么,要去模型选择器里一个个点开看。
 * 现在卡片上那一行是摘要 + 「查看模型」,点开是一张清单:名字、图像还是视频、能做哪几种生成、收哪些素材、
 * 有几个自己的参数(展开看是哪几个)。清单读的是缓存在模型行上的那一份,不现问插件 —— 要最新的点「刷新」。
 */

const MODE_LABELS: Record<string, MessageKey> = {
  "text-to-image": "genModeTextToImage",
  "image-to-image": "genModeImageToImage",
  "text-to-video": "genModeTextToVideo",
  "image-to-video": "genModeImageToVideo",
  "keyframes-to-video": "genModeKeyframesToVideo",
  "reference-to-video": "genModeReferenceToVideo",
  "video-edit": "genModeVideoEdit",
  "video-extend": "genModeVideoExtend",
};

const KIND_LABELS: Record<string, MessageKey> = {
  image: "pluginModelKind_image",
  video: "pluginModelKind_video",
};

/** 宿主自己有控件的那几项(尺寸、种子……)叫什么。和生成面板用的是同一份文案。 */
const HOST_PARAMETER_LABELS: Record<string, MessageKey> = {
  size: "genParam_size",
  seed: "genParam_seed",
  negative_prompt: "genParam_negative_prompt",
  num_images: "genParam_num_images",
  duration_seconds: "genParam_duration_seconds",
  resolution: "genParam_resolution",
  aspect_ratio: "genParam_aspect_ratio",
  generate_audio: "genParam_generate_audio",
};

const PARAMETER_TYPE_LABELS: Record<string, MessageKey> = {
  integer: "pluginParamType_integer",
  number: "pluginParamType_number",
  string: "pluginParamType_string",
  boolean: "pluginParamType_boolean",
};

/** 模型多到这个数就给一个搜索框。一台 ComfyUI 存几十张工作流是常事。 */
const SEARCH_THRESHOLD = 6;

export function GenerationModelsRow({
  instance,
  status,
  refreshing,
  onRefresh,
}: {
  instance: PluginInstance;
  status?: PluginCapabilityStatus;
  refreshing: boolean;
  onRefresh: () => void;
}) {
  const t = useI18n();
  const { locale } = usePreferences();
  const [open, setOpen] = React.useState(false);
  const models = status?.models;
  const summary = status?.error
    ? t("pluginGenerationError").replace("{error}", status.error)
    : models === null || models === undefined
      ? t("pluginGenerationNever")
      : t("pluginGenerationCount")
          .replace("{n}", String(models))
          .replace("{time}", status?.refreshed_at ? relativeTime(status.refreshed_at, locale) : "");
  return (
    <SettingsRow label={t("pluginGenerationModels")} description={t("pluginGenerationModelsDesc")}>
      <div className="flex min-w-0 items-center gap-2">
        <span className={cn("min-w-0 truncate text-ui-sm", status?.error ? "text-destructive" : "text-muted-foreground")}>
          {summary}
        </span>
        <Button variant="outline" disabled={!models} onClick={() => setOpen(true)}>
          {t("pluginModelsView")}
        </Button>
      </div>
      <ProvidedModelsDialog
        open={open}
        onOpenChange={setOpen}
        instance={instance}
        refreshedAt={status?.refreshed_at ?? null}
        refreshing={refreshing}
        onRefresh={onRefresh}
      />
    </SettingsRow>
  );
}

export function ProvidedModelsDialog({
  open,
  onOpenChange,
  instance,
  refreshedAt,
  refreshing,
  onRefresh,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  instance: PluginInstance;
  refreshedAt: string | null;
  refreshing: boolean;
  onRefresh: () => void;
}) {
  const t = useI18n();
  const { locale } = usePreferences();
  const [query, setQuery] = React.useState("");
  const models = useQuery({
    queryKey: ["plugin-models", instance.id],
    queryFn: () => listPluginInstanceModels(instance.id),
    enabled: open,
  });
  const all = models.data ?? [];
  const needle = query.trim().toLowerCase();
  const shown = needle
    ? all.filter((model) => `${model.label} ${model.id}`.toLowerCase().includes(needle))
    : all;
  return (
    <ModalShell
      open={open}
      onOpenChange={onOpenChange}
      title={t("pluginModelsTitle").replace("{name}", instance.name)}
      className="w-[680px] max-w-[calc(100vw-32px)]"
      header={
        all.length > SEARCH_THRESHOLD ? (
          <Input
            value={query}
            placeholder={t("pluginModelsSearch").replace("{n}", String(all.length))}
            onChange={(event) => setQuery(event.target.value)}
          />
        ) : undefined
      }
      footer={
        <div className="flex w-full items-center gap-2">
          {refreshedAt && (
            <span className="min-w-0 truncate text-ui-xs text-muted-foreground">
              {t("pluginModelsRefreshed").replace("{time}", relativeTime(refreshedAt, locale))}
            </span>
          )}
          <span className="flex-1" />
          <Button variant="outline" loading={refreshing} onClick={onRefresh}>
            <RefreshCcw size={13} />
            {t("pluginRefreshModels")}
          </Button>
        </div>
      }
    >
      {models.isLoading ? (
        <div className="grid gap-2">
          <Skeleton className="h-14" />
          <Skeleton className="h-14" />
        </div>
      ) : all.length === 0 ? (
        <p className="m-0 text-ui-sm text-muted-foreground">{t("pluginModelsEmpty")}</p>
      ) : shown.length === 0 ? (
        <p className="m-0 text-ui-sm text-muted-foreground">{t("pluginModelsNoMatch")}</p>
      ) : (
        <ul className="m-0 grid list-none gap-1.5 p-0">
          {shown.map((model) => (
            <ProvidedModelItem key={`${model.kind}:${model.id}`} model={model} />
          ))}
        </ul>
      )}
    </ModalShell>
  );
}

function ProvidedModelItem({ model }: { model: PluginProvidedModel }) {
  const t = useI18n();
  const [expanded, setExpanded] = React.useState(false);
  const kind = KIND_LABELS[model.kind];
  const modes = (model.modes ?? []).map((mode) => (MODE_LABELS[mode] ? t(MODE_LABELS[mode]) : mode));
  const inputs = (model.inputs ?? []).map((slot) => {
    const copy = ROLE_COPY[slot.role as SourceRole];
    const name = copy ? t(copy.label) : slot.role;
    const counted = slot.max > 1 ? `${name} ×${slot.max}` : name;
    return slot.required ? t("pluginModelRequired").replace("{role}", counted) : counted;
  });
  const parameters = model.parameters ?? [];
  const advanced = parameters.filter((parameter) => parameter.advanced).length;
  const hostParameters = (model.host_parameters ?? [])
    .map((key) => (HOST_PARAMETER_LABELS[key] ? t(HOST_PARAMETER_LABELS[key]) : ""))
    .filter(Boolean);
  const facts = [
    modes.join(" · "),
    inputs.length ? t("pluginModelTakes").replace("{roles}", inputs.join("、")) : t("pluginModelPromptOnly"),
  ].filter(Boolean);
  return (
    <li className="rounded-lg border border-border bg-card">
      <button
        type="button"
        className="flex w-full min-w-0 cursor-pointer items-start gap-2 rounded-lg px-3 py-2.5 text-left hover:bg-secondary"
        aria-expanded={expanded}
        onClick={() => setExpanded((value) => !value)}
      >
        <ChevronRight
          size={14}
          className={cn("mt-0.5 shrink-0 text-muted-foreground transition-transform duration-100", expanded && "rotate-90")}
        />
        <span className="grid min-w-0 flex-1 gap-0.5">
          <span className="flex min-w-0 items-center gap-2">
            <span className="min-w-0 truncate text-ui-sm font-medium text-foreground" title={model.id}>
              {model.label}
            </span>
            {kind && (
              <span className="shrink-0 rounded-full bg-secondary px-2 text-ui-2xs text-muted-foreground">{t(kind)}</span>
            )}
            {!model.enabled && (
              <span className="shrink-0 text-ui-2xs text-muted-foreground">{t("pluginModelDisabled")}</span>
            )}
          </span>
          <span className="text-ui-xs leading-[1.5] text-muted-foreground">{facts.join(" · ")}</span>
        </span>
        <span className="shrink-0 text-ui-xs text-muted-foreground">
          {t("pluginModelParams").replace("{n}", String(parameters.length))}
        </span>
      </button>
      {expanded && (
        <div className="grid gap-2 border-t border-border px-3 py-2.5 pl-9">
          {hostParameters.length > 0 && (
            <p className="m-0 text-ui-xs leading-[1.5] text-muted-foreground">{hostParameters.join(" · ")}</p>
          )}
          {parameters.length > 0 && (
            <ul className="m-0 grid list-none gap-1 p-0">
              {parameters.map((parameter) => (
                <li key={parameter.key} className="flex min-w-0 items-baseline gap-2 text-ui-xs">
                  <span className="min-w-0 truncate text-foreground" title={parameter.key}>
                    {parameter.title || parameter.key}
                  </span>
                  {PARAMETER_TYPE_LABELS[parameter.type] && (
                    <span className="shrink-0 text-muted-foreground">{t(PARAMETER_TYPE_LABELS[parameter.type])}</span>
                  )}
                </li>
              ))}
            </ul>
          )}
          {advanced > 0 && (
            <p className="m-0 text-ui-2xs text-muted-foreground">
              {t("pluginModelAdvancedParams").replace("{n}", String(advanced))}
            </p>
          )}
        </div>
      )}
    </li>
  );
}
