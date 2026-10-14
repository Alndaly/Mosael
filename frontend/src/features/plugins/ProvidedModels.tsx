import React from "react";

import type { LocalService, PluginCapabilityStatus, PluginInstance } from "@/api/client";
import { splitErrorText } from "@/api/errorMessage";
import type { MessageKey } from "@/app/messages";
import { useI18n, usePreferences } from "@/app/preferences";
import { SettingsRow } from "@/components/settings/settings-layout";
import { Truncate } from "@/components/ui/truncate";
import { ServiceIssueNote, focusConnectionSection, serviceIssue } from "@/features/plugins/localServiceStatus";
import { relativeTime } from "@/lib/time";
import { cn } from "@/lib/utils";

/**
 * 替宿主做生成的插件(ComfyUI 这类)**交出来了多少可生成的东西**。任何一个声明了 `provides: ["generation"]` 的
 * 插件都走这里,不认识哪一家。
 *
 * 这一行只摆**摘要**:几个、什么时候刷的、此刻刷不出来的原因。逐张看、按名字找是工具栏那颗「模型库 / 工作流库」的事
 * (同一张清单的完整窗口)——这里不再另开一个重复的「查看」入口。要最新一份点工具栏的「刷新」。
 */

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

export function GenerationModelsRow({
  instance,
  noun,
  status,
  service,
}: {
  instance: PluginInstance;
  /** 交出来的那一类东西叫什么(见 catalogNoun)。 */
  noun: string;
  status?: PluginCapabilityStatus;
  /** 连接背后的本机服务(没有是 null):目录没刷出来、而它此刻用不了时,按它的状态说(见 localServiceStatus)。 */
  service?: LocalService | null;
}) {
  const t = useI18n();
  const { locale } = usePreferences();
  const models = status?.models;
  const local = serviceIssue(service, Boolean(status?.error));
  //: 原因只说第一行那句人话;原文(errno、地址)悬停看
  const error = status?.error ? splitErrorText(status.error) : null;
  const refreshedAt = status?.refreshed_at ? relativeTime(status.refreshed_at, locale) : "";
  //: 刷不出来、手里还有上一次的清单(models 是上一次成功时的数):说清列着的是什么时候的
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
      </div>
    </SettingsRow>
  );
}
