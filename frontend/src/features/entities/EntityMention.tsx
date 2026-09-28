import React from "react";
import { useQuery } from "@tanstack/react-query";
import { AtSign } from "lucide-react";

import { assetThumbnailUrl, entityKeys, listEntities, type EntitySummary } from "@/api/client";
import { useI18n } from "@/app/preferences";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import type { ComposerChip } from "@/lib/composerChip";
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
 * AI 工作台的「@ 资产」:它的提示词框是一个普通文本框,没有画板那种 `@` 菜单,所以在输入卡底栏放一个 `@` 按钮挑 ——
 * 候选、每一行的长相和画板的 `@` 菜单是同一份(useMentionableEntities / EntityMentionRow)。挑中的和对话页的附件
 * 一样排在输入卡顶上(entityMentionChips → ComposerChips),提交时作为 `entity_ids` 交出去:提示词描述和参考图
 * 由服务端按模型收得下的张数挂上。
 *
 * 此前挑中的 chip 和「@ 资产」按钮自成一行,夹在正文和底栏之间(用户截图:位置很怪)。
 */
export function entityMentionChips(
  value: EntitySummary[],
  onChange: (next: EntitySummary[]) => void,
): ComposerChip[] {
  return value.map((one) => {
    const Icon = entityKindIcon(one.kind);
    return {
      id: `entity-${one.id}`,
      label: `@${entityDisplayName(one)}`,
      thumbnail: one.cover_asset_id ? assetThumbnailUrl(one.cover_asset_id) : undefined,
      icon: <Icon size={11} />,
      onRemove: () => onChange(value.filter((other) => other.id !== one.id)),
    };
  });
}

/** 底栏里的 `@` 按钮:挑一个资产加进这一次的引用。 */
export function EntityMentionButton({
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
    <>
      <Popover open={open} onOpenChange={setOpen}>
        <PopoverTrigger asChild>
          <Button type="button" variant="ghost" size="icon-xs" aria-label={t("entityMention")} title={t("entityMention")} data-entity-mention="">
            <AtSign size={14} />
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
    </>
  );
}
