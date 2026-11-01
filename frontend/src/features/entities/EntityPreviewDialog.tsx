import React from "react";
import { useQuery } from "@tanstack/react-query";

import { assetPreviewUrl, assetThumbnailUrl, entityKeys, getEntity, type EntitySummary } from "@/api/client";
import { useI18n } from "@/app/preferences";
import { ModalShell } from "@/components/app/modals";
import { FailureCard, rawFailureFields } from "@/components/failure/FailureCard";
import { InlineMarkdown } from "@/components/markdown/InlineMarkdown";
import { Button } from "@/components/ui/button";
import { FallbackImage } from "@/components/ui/fallback-image";
import { Skeleton } from "@/components/ui/skeleton";
import { Truncate } from "@/components/ui/truncate";
import { entityDisplayName, useCatalogLabels } from "./entityMeta";

/**
 * 点输入框里的 `@资产` 小条时先看这一眼:封面、种类、描述、提示词描述、标签和参考图。
 * 不把整个资产详情页塞进弹窗 —— 那里能改名、加图、跑任务;这里只回答「这次带上的是谁」。
 */
export function EntityPreviewDialog({
  workspaceId,
  entity,
  onClose,
}: {
  workspaceId: string;
  entity: EntitySummary | null;
  onClose: () => void;
}) {
  const t = useI18n();
  const labels = useCatalogLabels(Boolean(entity));
  const detail = useQuery({
    queryKey: entityKeys.detail(workspaceId, entity?.id ?? ""),
    queryFn: () => getEntity(entity!.id),
    enabled: Boolean(entity),
  });
  const shown = detail.data ?? entity;
  const cover = detail.data?.display_cover_asset_id || shown?.cover_asset_id || "";
  const references = (detail.data?.references ?? []).filter((one) => one.asset_kind === "image");
  const referenceCount = detail.data ? detail.data.references.length : entity?.reference_count ?? 0;
  const openDetail = () => {
    if (!entity) return;
    window.location.hash = `#/entities?entity=${encodeURIComponent(entity.id)}`;
    onClose();
  };
  return (
    <ModalShell
      open={Boolean(entity)}
      onOpenChange={(open) => !open && onClose()}
      title={shown ? entityDisplayName(shown) : ""}
      className="w-[min(640px,calc(100vw-32px))]"
      bodyClassName="grid gap-4"
      footer={
        <>
          <Button variant="outline" onClick={onClose}>{t("close")}</Button>
          <Button onClick={openDetail}>{t("entitiesOpen")}</Button>
        </>
      }
    >
      {entity && (
        <div className="grid gap-4" data-entity-preview="">
          {cover && (
            <div className="relative aspect-[16/9] overflow-hidden rounded-lg border border-border bg-panel-inset">
              <FallbackImage src={assetPreviewUrl(cover)} alt="" className="h-full w-full object-cover" />
            </div>
          )}

          <div className="flex flex-wrap items-center gap-2 text-ui-xs text-muted-foreground">
            <span className="rounded-full bg-secondary px-2 py-0.5 text-foreground">{labels.kind(shown?.kind ?? entity.kind)}</span>
            <span>{t("entityRefCount").replace("{n}", String(referenceCount))}</span>
            {detail.data && detail.data.variants.length > 0 && (
              <span>{t("entityVariantCount").replace("{n}", String(detail.data.variants.length))}</span>
            )}
          </div>

          {detail.isPending ? (
            <div className="grid gap-2">
              <Skeleton className="h-4 w-1/3" />
              <Skeleton className="h-16 w-full" />
            </div>
          ) : (
            <>
              {detail.data?.description && (
                <section className="grid gap-1.5">
                  <h3 className="m-0 text-ui-xs font-medium text-muted-foreground">{t("entityDescription")}</h3>
                  <div className="text-ui-sm leading-6 text-foreground"><InlineMarkdown text={detail.data.description} /></div>
                </section>
              )}
              {detail.data?.prompt && (
                <section className="grid gap-1.5">
                  <h3 className="m-0 text-ui-xs font-medium text-muted-foreground">{t("entityPrompt")}</h3>
                  <p className="m-0 whitespace-pre-wrap rounded-md bg-muted px-3 py-2 text-ui-sm leading-6 text-foreground">{detail.data.prompt}</p>
                </section>
              )}
              {detail.data?.tags?.length ? (
                <div className="flex flex-wrap gap-1.5">
                  {detail.data.tags.map((tag) => <span key={tag} className="rounded-sm bg-secondary px-1.5 py-0.5 text-ui-2xs text-muted-foreground">{tag}</span>)}
                </div>
              ) : null}
              {references.length > 0 && (
                <section className="grid gap-1.5">
                  <h3 className="m-0 text-ui-xs font-medium text-muted-foreground">{t("entityReferences")}</h3>
                  <div className="grid grid-cols-4 gap-2">
                    {references.slice(0, 8).map((one) => (
                      <div key={one.asset_id} className="relative aspect-square overflow-hidden rounded-md border border-border bg-panel-inset">
                        <FallbackImage src={assetThumbnailUrl(one.asset_id)} alt="" className="h-full w-full object-cover" loading="lazy" />
                        <Truncate className="absolute inset-x-0 bottom-0 bg-[rgba(10,12,15,0.72)] px-1 py-0.5 text-[10px] text-[#e8eaed]">
                          {labels.role(one.role)}
                        </Truncate>
                      </div>
                    ))}
                  </div>
                </section>
              )}
            </>
          )}
          {detail.isError && (
            <FailureCard size="compact" title={t("pageLoadError")} {...rawFailureFields(detail.error.message, t("pageLoadError"))} />
          )}
        </div>
      )}
    </ModalShell>
  );
}
