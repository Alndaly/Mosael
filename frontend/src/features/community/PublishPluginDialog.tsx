import React from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Send } from "lucide-react";
import { toast } from "sonner";

import { publishPluginToCommunity, type CommunityPublishResult } from "@/api/client";
import { useI18n } from "@/app/preferences";
import { DIALOG_FIELD, ModalShell } from "@/components/app/modals";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { COMMUNITY_STATUS_KEY } from "@/features/community/communityShared";
import { PublishedResult, parseTags } from "@/features/community/publishShared";

/**
 * 插件的「发布到社区」(ADR 0026 §4):给写插件的人用。
 *
 * 后端把插件目录打成和发版同一种 zip(只打受版本管理的文件,去掉缓存和一切像密钥的东西),用「从文件安装」
 * 那一套规则自己验一遍,再上传。插件会在别人的电脑上跑代码,所以先进审核 —— 发完这里显示「审核中」。
 */
export function PublishPluginDialog({
  open,
  onOpenChange,
  plugin,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  plugin: { id: string; name: string; version: string };
}) {
  const t = useI18n();
  const qc = useQueryClient();
  const [summary, setSummary] = React.useState("");
  const [tags, setTags] = React.useState("");
  const [result, setResult] = React.useState<CommunityPublishResult | null>(null);

  React.useEffect(() => {
    if (!open) return;
    setSummary("");
    setTags("");
    setResult(null);
  }, [open, plugin.id]);

  const publish = useMutation({
    mutationFn: () => publishPluginToCommunity(plugin.id, { summary: summary.trim(), tags: parseTags(tags) }),
    onSuccess: setResult,
    onError: (error: Error) => {
      toast.error(error.message);
      void qc.invalidateQueries({ queryKey: COMMUNITY_STATUS_KEY });
    },
  });

  return (
    <ModalShell
      open={open}
      onOpenChange={(next) => !publish.isPending && onOpenChange(next)}
      title={t("communityPublishPlugin").replace("{name}", plugin.name)}
      className="w-[500px]"
      footer={
        result ? (
          <Button onClick={() => onOpenChange(false)}>{t("communityDone")}</Button>
        ) : (
          <>
            <Button variant="outline" disabled={publish.isPending} onClick={() => onOpenChange(false)}>
              {t("cancel")}
            </Button>
            <Button loading={publish.isPending} onClick={() => publish.mutate()}>
              <Send /> {t("communityPublish")}
            </Button>
          </>
        )
      }
    >
      {result ? (
        <PublishedResult result={result} />
      ) : (
        <div className="grid gap-4" data-testid="publish-plugin-form">
          <p className="m-0 text-ui-sm leading-relaxed text-muted-foreground">
            {t("communityPublishPluginIntro").replace("{version}", plugin.version)}
          </p>
          <label className={DIALOG_FIELD}>
            <span>{t("communityFieldSummary")}</span>
            <Textarea value={summary} rows={3} maxLength={2000} onChange={(event) => setSummary(event.currentTarget.value)} />
          </label>
          <label className={DIALOG_FIELD}>
            <span>{t("communityFieldTags")}</span>
            <Input value={tags} placeholder={t("communityFieldTagsPlaceholder")} onChange={(event) => setTags(event.currentTarget.value)} />
          </label>
        </div>
      )}
    </ModalShell>
  );
}
