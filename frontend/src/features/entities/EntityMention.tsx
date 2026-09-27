import React from "react";
import { useQuery } from "@tanstack/react-query";
import { AtSign, X } from "lucide-react";

import { assetThumbnailUrl, entityKeys, listEntities, type EntitySummary } from "@/api/client";
import { useI18n } from "@/app/preferences";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { cn } from "@/lib/utils";
import { entityDisplayName, entityKindIcon, useCatalogLabels } from "@/features/entities/entityMeta";

/** 一个资产的小方块:有封面画封面,没有画种类的图标。菜单行、弹窗行、正文里的 chip 共用。 */
export function EntityThumb({ entity, className }: { entity: Pick<EntitySummary, "kind" | "cover_asset_id">; className?: string }) {
  const Icon = entityKindIcon(entity.kind);
  const [broken, setBroken] = React.useState(false);
  return entity.cover_asset_id && !broken ? (
    <img
      src={assetThumbnailUrl(entity.cover_asset_id)}
      alt=""
      className={cn("h-8 w-8 shrink-0 rounded bg-control object-cover", className)}
      onError={() => setBroken(true)}
    />
  ) : (
    <span className={cn("grid h-8 w-8 shrink-0 place-items-center rounded bg-control text-muted-foreground", className)}>
      <Icon size={15} />
    </span>
  );
}

/**
 * `@` 菜单里的一行资产:封面(或种类图标)、名字、种类。画板提示词框的 `@` 菜单(PromptEditor)和 AI 工作台的
 * 「@ 资产」挑选读的是这一行 —— 一种长相,不在两处各画一遍。
 */
export function EntityMentionRow({ entity, showKind = true }: { entity: EntitySummary; showKind?: boolean }) {
  const labels = useCatalogLabels();
  const Icon = entityKindIcon(entity.kind);
  return (
    <>
      <span className="relative shrink-0">
        <EntityThumb entity={entity} className="h-8 w-10" />
        <span className="absolute -bottom-0.5 -right-0.5 grid h-3.5 w-3.5 place-items-center rounded-full bg-panel text-muted-foreground">
          <Icon size={9} />
        </span>
      </span>
      <span className="min-w-0 flex-1 truncate text-ui-xs text-foreground">{entityDisplayName(entity)}</span>
      {showKind && <span className="shrink-0 text-ui-2xs text-muted-foreground">{labels.kind(entity.kind)}</span>}
    </>
  );
}

/** 这个工作区的资产(含变体),`@` 菜单的候选。按名字筛,由调用方截断。 */
export function useMentionableEntities(workspaceId: string | undefined, enabled = true) {
  return useQuery({
    queryKey: entityKeys.list(workspaceId ?? "", { includeVariants: true }),
    queryFn: () => listEntities(workspaceId ?? "", { includeVariants: true }),
    enabled: Boolean(workspaceId) && enabled,
    staleTime: 30_000,
  });
}

export function matchEntities(entities: EntitySummary[] | undefined, query: string): EntitySummary[] {
  const needle = query.trim().toLowerCase();
  return (entities ?? []).filter((one) => !needle || entityDisplayName(one).toLowerCase().includes(needle));
}

/**
 * AI 工作台的「@ 资产」:它的提示词框是一个普通文本框,没有画板那种 `@` 菜单,所以在框下面挑 —— 候选、每一行的
 * 长相和画板的 `@` 菜单是同一份(useMentionableEntities / EntityMentionRow)。挑中的排成一排 chip,
 * 提交时作为 `entity_ids` 交出去:提示词描述和参考图由服务端按模型收得下的张数挂上。
 */
export function EntityMentionPicker({
  workspaceId,
  value,
  onChange,
}: {
  workspaceId: string;
  value: EntitySummary[];
  onChange: (next: EntitySummary[]) => void;
}) {
  const t = useI18n();
  const [open, setOpen] = React.useState(false);
  const [query, setQuery] = React.useState("");
  //: 挑的时候才取 —— 工作台一打开就取一份用不上的清单没有意义。
  const entities = useMentionableEntities(workspaceId, open);
  const picked = new Set(value.map((one) => one.id));
  const candidates = matchEntities(entities.data, query).filter((one) => !picked.has(one.id)).slice(0, 12);
  return (
    <div className="flex min-w-0 flex-wrap items-center gap-1" data-entity-mentions="">
      {value.map((one) => (
        <span key={one.id} className="inline-flex max-w-[200px] items-center gap-1 rounded-md bg-secondary py-0.5 pl-1 pr-0.5 text-ui-2xs text-foreground" data-entity-chip={one.id}>
          <EntityThumb entity={one} className="h-4 w-4 rounded-[3px]" />
          <span className="truncate">@{entityDisplayName(one)}</span>
          <button
            type="button"
            className="grid size-4 cursor-pointer place-items-center rounded border-0 bg-transparent text-muted-foreground hover:text-foreground"
            aria-label={t("entityMentionRemove").replace("{name}", entityDisplayName(one))}
            onClick={() => onChange(value.filter((other) => other.id !== one.id))}
          >
            <X size={11} />
          </button>
        </span>
      ))}
      <Popover open={open} onOpenChange={setOpen}>
        <PopoverTrigger asChild>
          <Button type="button" variant="ghost" size="xs" className="gap-1 text-muted-foreground hover:text-foreground" aria-label={t("entityMention")}>
            <AtSign size={13} />
            {t("entityMention")}
          </Button>
        </PopoverTrigger>
        <PopoverContent align="start" className="grid w-[320px] gap-1.5 p-1.5">
          <Input
            size="sm"
            autoFocus
            aria-label={t("entityPickSearch")}
            placeholder={t("entityPickSearch")}
            value={query}
            onChange={(event) => setQuery(event.target.value)}
          />
          {candidates.length === 0 ? (
            <p className="m-0 px-1.5 py-2 text-ui-xs text-muted-foreground">
              {t(entities.data?.length ? "entityPickNoMatches" : "entityPickNone")}
            </p>
          ) : (
            <div className="grid max-h-72 overflow-y-auto">
              {candidates.map((one) => (
                <button
                  key={one.id}
                  type="button"
                  className="flex w-full cursor-pointer items-center gap-2 rounded-md border-0 bg-transparent px-1.5 py-1 text-left hover:bg-secondary"
                  onClick={() => {
                    onChange([...value, one]);
                    setQuery("");
                    setOpen(false);
                  }}
                >
                  <EntityMentionRow entity={one} />
                </button>
              ))}
            </div>
          )}
          <p className="m-0 border-t border-border px-1.5 pt-1 text-ui-2xs text-muted-foreground">{t("entityMentionHint")}</p>
        </PopoverContent>
      </Popover>
    </div>
  );
}
