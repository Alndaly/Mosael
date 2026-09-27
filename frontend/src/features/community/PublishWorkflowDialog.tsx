import React from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ImageIcon, Send, X } from "lucide-react";
import { toast } from "sonner";

import { assetKeys } from "@/api/queryKeys";
import {
  assetThumbnailUrl,
  listAssets,
  publishWorkflowToCommunity,
  type Asset,
  type CommunityPublishResult,
  type Workflow,
} from "@/api/client";
import { useI18n } from "@/app/preferences";
import { PickListDialog } from "@/components/app/PickListDialog";
import { DIALOG_FIELD, ModalShell } from "@/components/app/modals";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { COMMUNITY_STATUS_KEY } from "@/features/community/communityShared";
import { PublishedResult, parseTags } from "@/features/community/publishShared";

/**
 * 工作流的「发布到社区」(ADR 0026 §4)。发的是本机「导出」得到的那同一份文件,加上标题、简介、标签和
 * 一张封面(从素材库里挑)。发布即上架;第一次是一个新条目,之后再发就是**这一条的新版本**(后端记着 slug)。
 */
export function PublishWorkflowDialog({
  open,
  onOpenChange,
  workflow,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  workflow: Workflow;
}) {
  const t = useI18n();
  const qc = useQueryClient();
  const [title, setTitle] = React.useState(workflow.name);
  const [summary, setSummary] = React.useState(workflow.description);
  const [tags, setTags] = React.useState("");
  const [cover, setCover] = React.useState<Asset | null>(null);
  const [picking, setPicking] = React.useState(false);
  const [result, setResult] = React.useState<CommunityPublishResult | null>(null);
  const republish = Boolean(workflow.community_slug);

  React.useEffect(() => {
    if (!open) return;
    setTitle(workflow.name);
    setSummary(workflow.description);
    setTags("");
    setCover(null);
    setResult(null);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, workflow.id]);

  const publish = useMutation({
    mutationFn: () =>
      publishWorkflowToCommunity(workflow.id, {
        title: title.trim(),
        summary: summary.trim(),
        tags: parseTags(tags),
        cover_asset_id: cover?.id ?? null,
      }),
    onSuccess: (published) => {
      setResult(published);
      void qc.invalidateQueries({ queryKey: ["workflows", workflow.workspace_id] });
    },
    onError: (error: Error) => {
      toast.error(error.message);
      void qc.invalidateQueries({ queryKey: COMMUNITY_STATUS_KEY });
    },
  });

  return (
    <ModalShell
      open={open}
      onOpenChange={(next) => !publish.isPending && onOpenChange(next)}
      title={republish ? t("communityPublishNewVersion") : t("communityPublishWorkflow")}
      className="w-[520px]"
      footer={
        result ? (
          <Button onClick={() => onOpenChange(false)}>{t("communityDone")}</Button>
        ) : (
          <>
            <Button variant="outline" disabled={publish.isPending} onClick={() => onOpenChange(false)}>
              {t("cancel")}
            </Button>
            <Button loading={publish.isPending} disabled={!title.trim()} onClick={() => publish.mutate()}>
              <Send /> {republish ? t("communityPublishNewVersion") : t("communityPublish")}
            </Button>
          </>
        )
      }
    >
      {result ? (
        <PublishedResult result={result} />
      ) : (
        <div className="grid gap-4" data-testid="publish-workflow-form">
          <p className="m-0 text-ui-sm leading-relaxed text-muted-foreground">
            {republish ? t("communityPublishWorkflowAgain") : t("communityPublishWorkflowIntro")}
          </p>
          <label className={DIALOG_FIELD}>
            <span>{t("communityFieldTitle")}</span>
            <Input value={title} maxLength={120} onChange={(event) => setTitle(event.currentTarget.value)} />
          </label>
          <label className={DIALOG_FIELD}>
            <span>{t("communityFieldSummary")}</span>
            <Textarea value={summary} rows={3} maxLength={2000} onChange={(event) => setSummary(event.currentTarget.value)} />
          </label>
          <label className={DIALOG_FIELD}>
            <span>{t("communityFieldTags")}</span>
            <Input value={tags} placeholder={t("communityFieldTagsPlaceholder")} onChange={(event) => setTags(event.currentTarget.value)} />
          </label>
          <div className="grid gap-2">
            <span className="text-ui-sm font-medium text-foreground">{t("communityFieldCover")}</span>
            {cover ? (
              <span className="flex min-w-0 items-center gap-3">
                <span className="shrink-0">
                  <img src={assetThumbnailUrl(cover.id)} alt="" className="h-14 w-20 rounded-md object-cover" />
                </span>
                <span className="min-w-0 flex-1 truncate text-ui-sm">{cover.name}</span>
                <Button variant="ghost" size="icon-sm" aria-label={t("communityCoverRemove")} title={t("communityCoverRemove")} onClick={() => setCover(null)}>
                  <X />
                </Button>
              </span>
            ) : (
              <Button variant="outline" className="w-fit" onClick={() => setPicking(true)}>
                <ImageIcon /> {t("communityCoverPick")}
              </Button>
            )}
          </div>
        </div>
      )}
      <CoverPicker
        open={picking}
        workspaceId={workflow.workspace_id}
        onOpenChange={setPicking}
        onPick={(asset) => {
          setCover(asset);
          setPicking(false);
        }}
      />
    </ModalShell>
  );
}

/** 从素材库里挑一张图当封面。 */
function CoverPicker({
  open,
  workspaceId,
  onOpenChange,
  onPick,
}: {
  open: boolean;
  workspaceId: string;
  onOpenChange: (open: boolean) => void;
  onPick: (asset: Asset) => void;
}) {
  const t = useI18n();
  const [keyword, setKeyword] = React.useState("");
  const assets = useQuery({ queryKey: assetKeys.list(workspaceId), queryFn: () => listAssets(workspaceId), enabled: open });
  const images = React.useMemo(() => {
    const needle = keyword.trim().toLowerCase();
    return (assets.data ?? []).filter(
      (asset: Asset) =>
        asset.kind === "image" && (!needle || `${asset.name ?? ""} ${asset.original_filename ?? ""}`.toLowerCase().includes(needle)),
    );
  }, [assets.data, keyword]);
  return (
    <PickListDialog
      open={open}
      onOpenChange={onOpenChange}
      title={t("communityCoverPick")}
      searchLabel={t("boardsSearchImages")}
      query={keyword}
      onQueryChange={setKeyword}
      items={images}
      itemKey={(asset) => asset.id}
      row={(asset) => ({
        lead: <img src={assetThumbnailUrl(asset.id)} alt="" loading="lazy" className="h-full w-full object-cover" />,
        title: asset.name || asset.original_filename || "",
      })}
      onPick={onPick}
      pending={assets.isLoading}
      error={assets.isError ? assets.error.message : null}
      onRetry={() => void assets.refetch()}
      empty={{ icon: <ImageIcon size={24} strokeWidth={1.5} />, text: t("boardsNoImages") }}
    />
  );
}
