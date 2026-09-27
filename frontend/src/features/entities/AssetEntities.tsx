import React from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import {
  addEntityReference,
  entityKeys,
  listAssetEntities,
  listEntities,
  type Asset,
  type EntityKind,
} from "@/api/client";
import { errorText } from "@/api/errorMessage";
import { useI18n } from "@/app/preferences";
import { ModalShell } from "@/components/app/modals";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { OptionPicker } from "@/components/ui/option-picker";
import { entityDisplayName, entityKindIcon, useCatalogLabels } from "@/features/entities/entityMeta";

/** 去资产库里打开这一个资产(深链见 EntitiesView)。 */
export function openEntity(id: string) {
  window.location.hash = `#/entities?entity=${encodeURIComponent(id)}`;
}

/**
 * 素材详情里的「属于哪些资产」:这张图是谁的正面、哪个场景的设定图。点一下去那个资产。
 * 删这份素材时,这些资产会各少一张参考图(资产本身不动)。
 */
export function AssetEntitiesList({ asset }: { asset: Pick<Asset, "id" | "workspace_id"> }) {
  const t = useI18n();
  const labels = useCatalogLabels();
  const rows = useQuery({
    queryKey: entityKeys.ofAsset(asset.workspace_id, asset.id),
    queryFn: () => listAssetEntities(asset.id),
  });
  if (rows.isPending) return <span className="text-muted-foreground">{t("pageLoading")}</span>;
  if (!rows.data?.length) return <span className="text-muted-foreground">{t("assetEntitiesNone")}</span>;
  return (
    <ul className="m-0 grid list-none gap-1 p-0" data-asset-entities="">
      {rows.data.map((row) => {
        const Icon = entityKindIcon(row.kind);
        return (
          <li key={row.id}>
            <button
              type="button"
              className="inline-flex max-w-full cursor-pointer items-center gap-1.5 rounded-sm border-0 bg-transparent p-0 text-left text-ui-sm text-foreground hover:text-primary"
              onClick={() => openEntity(row.id)}
            >
              <Icon size={13} className="shrink-0 text-muted-foreground" />
              <span className="truncate">{entityDisplayName(row)}</span>
              <span className="shrink-0 text-ui-xs text-muted-foreground">{labels.role(row.role)}</span>
            </button>
          </li>
        );
      })}
    </ul>
  );
}

const DEFAULT_ROLE: Record<EntityKind, string> = { character: "front", location: "concept", prop: "front" };

/**
 * 素材库右键「设为某个资产的参考图…」:挑一个资产、挑角度(可以顺手设成封面)。
 * 同一张图已经是它的参考图时,效果是换个角度 —— 和详情页里挂图同一个接口。
 */
export function SetAsReferenceDialog({
  asset,
  onClose,
}: {
  asset: Asset | null;
  onClose: () => void;
}) {
  const t = useI18n();
  const qc = useQueryClient();
  const labels = useCatalogLabels(asset !== null);
  const workspaceId = asset?.workspace_id ?? "";
  const entities = useQuery({
    queryKey: entityKeys.list(workspaceId, { includeVariants: true }),
    queryFn: () => listEntities(workspaceId, { includeVariants: true }),
    enabled: Boolean(asset),
  });
  const [entityId, setEntityId] = React.useState("");
  const [role, setRole] = React.useState("");
  const [cover, setCover] = React.useState(false);
  React.useEffect(() => {
    setEntityId("");
    setRole("");
    setCover(false);
  }, [asset?.id]);
  const chosen = (entities.data ?? []).find((one) => one.id === entityId);
  //: 角度按这个资产的种类列:换了一个资产(人物换成场景),原来挑的「正面」场景没有,落回它的缺省。
  const roleOptions = chosen ? labels.rolesFor(chosen.kind) : [];
  const effectiveRole = roleOptions.some((one) => one.value === role) ? role : chosen ? DEFAULT_ROLE[chosen.kind] : "";

  const attach = useMutation({
    mutationFn: () => addEntityReference(entityId, { asset_id: asset!.id, role: effectiveRole, cover: cover && asset?.kind === "image" }),
    onSuccess: (entity) => {
      void qc.invalidateQueries({ queryKey: entityKeys.all(workspaceId) });
      toast.success(
        t("assetSetAsReferenceDone").replace("{name}", entityDisplayName(entity)).replace("{role}", labels.role(effectiveRole)),
      );
      onClose();
    },
    onError: (error) => toast.error(errorText(error)),
  });

  return (
    <ModalShell
      open={asset !== null}
      onOpenChange={(open) => !open && !attach.isPending && onClose()}
      title={t("assetSetAsReferenceTitle")}
      footer={
        <>
          <Button variant="outline" disabled={attach.isPending} onClick={onClose}>
            {t("cancel")}
          </Button>
          <Button disabled={!entityId} loading={attach.isPending} onClick={() => attach.mutate()}>
            {t("confirm")}
          </Button>
        </>
      }
    >
      <div className="grid gap-4" data-set-as-reference="">
        <p className="m-0 text-ui-sm text-muted-foreground">{t("assetSetAsReferenceHint").replace("{name}", asset?.name ?? "")}</p>
        <label className="grid gap-1.5">
          <span className="text-ui-sm font-medium">{t("entityPickTitle")}</span>
          <OptionPicker
            ariaLabel={t("entityPickTitle")}
            value={entityId}
            onChange={setEntityId}
            placeholder={t(entities.data?.length ? "entityPickPlaceholder" : "entityPickNone")}
            disabled={!entities.data?.length}
            options={(entities.data ?? []).map((one) => ({ value: one.id, label: `${labels.kind(one.kind)} · ${entityDisplayName(one)}` }))}
          />
        </label>
        <label className="grid gap-1.5">
          <span className="text-ui-sm font-medium">{t("entityRole")}</span>
          <OptionPicker ariaLabel={t("entityRole")} value={effectiveRole} onChange={setRole} options={roleOptions} disabled={!entityId} />
        </label>
        {asset?.kind === "image" && (
          <label className="flex items-center gap-2 text-ui-sm">
            <Checkbox checked={cover} onCheckedChange={(on) => setCover(on === true)} />
            {t("entitySetCover")}
          </label>
        )}
      </div>
    </ModalShell>
  );
}
