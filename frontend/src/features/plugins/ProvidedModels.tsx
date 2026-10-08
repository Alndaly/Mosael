import React from "react";
import { useQuery } from "@tanstack/react-query";
import { AlertTriangle, ChevronRight, RefreshCcw } from "lucide-react";

import {
  listPluginInstanceModels,
  type LocalService,
  type PluginCapabilityStatus,
  type PluginInstance,
  type PluginProvidedModel,
} from "@/api/client";
import { splitErrorText } from "@/api/errorMessage";
import type { MessageKey } from "@/app/messages";
import { useI18n, usePreferences } from "@/app/preferences";
import { ModalShell } from "@/components/app/modals";
import { SettingsRow } from "@/components/settings/settings-layout";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { Hint } from "@/components/ui/tooltip";
import { Truncate } from "@/components/ui/truncate";
import { ServiceIssueNote, focusConnectionSection, serviceIssue } from "@/features/plugins/localServiceStatus";
import { entryOrigin, formedGroups } from "@/lib/entryNames";
import { ROLE_COPY, type SourceRole } from "@/lib/sourceFrames";
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
  "speech-to-video": "genModeSpeechToVideo",
  "video-lipsync": "genModeVideoLipsync",
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

/**
 * 这个插件交出来的那一类东西叫什么:清单的 `generation_noun`(ComfyUI 是「工作流」,已按语言挑好),没写就是「模型」。
 * 宿主不认识哪一家 —— ComfyUI 交的是工作流和表单,此前这里一律叫「模型」,人会去找 checkpoint。
 */
export function catalogNoun(pkg: { generation_noun?: string }, t: (key: MessageKey) => string): string {
  return pkg.generation_noun?.trim() || t("pluginGenerationNoun");
}

/** 把文案里的 `{noun}` 换成这个词;`{Noun}` 是句首那一处(英文首字母大写,中文原样)。 */
export function withNoun(text: string, noun: string): string {
  return text.replaceAll("{noun}", noun).replaceAll("{Noun}", noun.charAt(0).toUpperCase() + noun.slice(1));
}

/** 模型多到这个数就给一个搜索框。一台 ComfyUI 存几十张工作流是常事。 */
const SEARCH_THRESHOLD = 6;

export function GenerationModelsRow({
  instance,
  noun,
  status,
  service,
  refreshing,
  onRefresh,
}: {
  instance: PluginInstance;
  /** 交出来的那一类东西叫什么(见 catalogNoun)。 */
  noun: string;
  status?: PluginCapabilityStatus;
  /** 连接背后的本机服务(没有是 null):目录没刷出来、而它此刻用不了时,按它的状态说(见 localServiceStatus)。 */
  service?: LocalService | null;
  refreshing: boolean;
  onRefresh: () => void;
}) {
  const t = useI18n();
  const { locale } = usePreferences();
  const [open, setOpen] = React.useState(false);
  const models = status?.models;
  const local = serviceIssue(service, Boolean(status?.error));
  //: 原因只说第一行那句人话;原文(errno、地址)悬停看
  const error = status?.error ? splitErrorText(status.error) : null;
  const refreshedAt = status?.refreshed_at ? relativeTime(status.refreshed_at, locale) : "";
  //: 刷不出来、手里还有上一次的清单(models 是上一次成功时的数):说清列着的是什么时候的,和清单弹窗顶上那句一致
  const stale = Boolean(error) && typeof models === "number" && Boolean(status?.refreshed_at);
  const summary = error
    ? (stale ? t("pluginGenerationStale").replace("{time}", refreshedAt) : t("pluginGenerationError")).replace("{error}", error.summary)
    : models === null || models === undefined
      ? t("pluginGenerationNever")
      : withNoun(t("pluginGenerationCount"), noun).replace("{n}", String(models)).replace("{time}", refreshedAt);
  return (
    <SettingsRow label={withNoun(t("pluginGenerationModels"), noun)} description={withNoun(t("pluginGenerationModelsDesc"), noun)}>
      <div className="flex min-w-0 items-center gap-2">
        {local && service ? (
          // 本机服务此刻用不了:说它的状态(停着给「启动」、起不来给「日志」),不说插件那句「检查地址」
          <ServiceIssueNote instanceId={instance.id} service={service} issue={local} className="max-w-[22rem]"
                            onInstall={() => focusConnectionSection(instance.id, "local-service")} />
        ) : (
          <Truncate
            className={cn("max-w-[22rem] text-ui-sm", status?.error ? "text-destructive" : "text-muted-foreground")}
            hint={error?.detail || undefined}
          >
            {summary}
          </Truncate>
        )}
        <Button variant="outline" disabled={!models} onClick={() => setOpen(true)}>
          {withNoun(t("pluginModelsView"), noun)}
        </Button>
      </div>
      <ProvidedModelsDialog
        open={open}
        onOpenChange={setOpen}
        instance={instance}
        noun={noun}
        staleBecause={stale ? error!.summary : null}
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
  noun,
  staleBecause,
  refreshedAt,
  refreshing,
  onRefresh,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  instance: PluginInstance;
  noun: string;
  /** 现在刷不出来的那句人话(连不上这台 ComfyUI……);null = 清单是好的。有它时顶上说清这是哪一次的清单、给「重新连接」。 */
  staleBecause: string | null;
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
  //: 按名字、模型 id、它来自的那张工作流的名字都搜得到(ADR 0045)
  const shown = needle
    ? all.filter((model) => `${model.label} ${model.id} ${model.group?.label ?? ""}`.toLowerCase().includes(needle))
    : all;
  const formed = formedGroups(all);
  const stale = Boolean(staleBecause);
  return (
    <ModalShell
      open={open}
      onOpenChange={onOpenChange}
      title={withNoun(t("pluginModelsTitle"), noun).replace("{name}", instance.name)}
      className="w-[680px] max-w-[calc(100vw-32px)]"
      header={
        stale || all.length > SEARCH_THRESHOLD ? (
          <div className="grid gap-2">
            {stale && (
              //: 现在刷不出来:下面是上一次的清单,不是现在能用的样子 —— 先说清,给「重新连接」(就是再刷一次)
              <div role="status" data-catalog-stale=""
                   className="flex min-w-0 items-center gap-2 rounded-md border border-warning/40 bg-warning/10 px-3 py-2">
                <AlertTriangle size={14} className="shrink-0 text-warning" />
                <span className="min-w-0 flex-1 text-ui-sm text-foreground">
                  {t("pluginModelsStale").replace("{time}", refreshedAt ? relativeTime(refreshedAt, locale) : "").replace("{error}", staleBecause ?? "")}
                </span>
                <Button size="sm" variant="outline" loading={refreshing} onClick={onRefresh}>
                  {t("pluginModelsReconnect")}
                </Button>
              </div>
            )}
            {all.length > SEARCH_THRESHOLD && (
              <Input
                value={query}
                placeholder={withNoun(t("pluginModelsSearch"), noun).replace("{n}", String(all.length))}
                onChange={(event) => setQuery(event.target.value)}
              />
            )}
          </div>
        ) : undefined
      }
      footer={
        <div className="flex w-full items-center gap-2">
          {/* 刷不出来时什么时候的清单已经在顶上那句里了,这里不再写一句看起来像「刚刷过」的时间 */}
          {refreshedAt && !stale && (
            <Truncate className="text-ui-xs text-muted-foreground">
              {t("pluginModelsRefreshed").replace("{time}", relativeTime(refreshedAt, locale))}
            </Truncate>
          )}
          <span className="flex-1" />
          <Button variant="outline" loading={refreshing} onClick={onRefresh}>
            <RefreshCcw size={13} />
            {withNoun(t("pluginRefreshModels"), noun)}
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
        <p className="m-0 text-ui-sm text-muted-foreground">{withNoun(t("pluginModelsEmpty"), noun)}</p>
      ) : shown.length === 0 ? (
        <p className="m-0 text-ui-sm text-muted-foreground">{withNoun(t("pluginModelsNoMatch"), noun)}</p>
      ) : (
        //: 刷不出来时清单整体压暗一档:是上一次的样子,不是现在能用的
        <ul className={cn("m-0 grid list-none gap-1.5 p-0", stale && "opacity-70")} data-stale={stale ? "" : undefined}>
          {shown.map((model) => (
            <ProvidedModelItem key={`${model.kind}:${model.id}`} model={model} origin={entryOrigin(model.group, formed, t)} />
          ))}
        </ul>
      )}
    </ModalShell>
  );
}

/** `origin`:两层名字的副名里「这是哪个入口」那一截(「来自 X」/「完整工作流」,ADR 0045);空串就不写。整张弹窗说的是
 *  一个连接,连接名不再写。 */
function ProvidedModelItem({ model, origin }: { model: PluginProvidedModel; origin: string }) {
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
    //: 表单入口和别的项左边对齐,第二行写「来自 X」—— 不再往右缩一截(和下拉、「添加节点」同一种摆法,ADR 0045)
    <li className="rounded-lg border border-border bg-card" data-entry={model.group?.entry}>
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
            {/* 显示名在前;悬停给模型 id(供应商认的那个)。 */}
            <Hint label={model.id !== model.label ? model.id : undefined}>
              <Truncate className="text-ui-sm font-medium text-foreground">{model.label}</Truncate>
            </Hint>
            {kind && (
              <span className="shrink-0 rounded-full bg-secondary px-2 text-ui-2xs text-muted-foreground">{t(kind)}</span>
            )}
            {!model.enabled && (
              <span className="shrink-0 text-ui-2xs text-muted-foreground">{t("pluginModelDisabled")}</span>
            )}
          </span>
          {origin && <span className="text-ui-xs text-muted-foreground" data-entry-origin="">{origin}</span>}
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
                  {/* 悬停给工作流里的参数键(节点.字段),显示名就是键时不重复。 */}
                  <Hint label={parameter.title ? parameter.key : undefined}>
                    <Truncate className="text-foreground">{parameter.title || parameter.key}</Truncate>
                  </Hint>
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
