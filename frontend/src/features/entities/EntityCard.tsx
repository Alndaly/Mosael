import React from "react";

import { assetThumbnailUrl, type EntitySummary } from "@/api/client";
import { useI18n } from "@/app/preferences";
import { cn } from "@/lib/utils";
import { entityKindIcon } from "@/features/entities/entityMeta";

/**
 * 一张封面卡:封面、名字、参考图和变体的张数、标签。没有封面时是种类的图标。
 *
 * `tile`:和参考图卡片同一种样子(正方形、同样的圆角和边框、下面一行小字)—— 详情页里变体和参考图挨着看,
 * 一个是竖长大卡、一个是方格的话,读起来是两种东西。资产库列表页用默认的大卡。
 */
export function EntityCard({
  entity,
  onOpen,
  selected = false,
  tile = false,
}: {
  entity: EntitySummary;
  onOpen: () => void;
  selected?: boolean;
  tile?: boolean;
}) {
  const t = useI18n();
  const Icon = entityKindIcon(entity.kind);
  const [broken, setBroken] = React.useState(false);
  const meta = [
    t("entityRefCount").replace("{n}", String(entity.reference_count)),
    entity.variant_count ? t("entityVariantCount").replace("{n}", String(entity.variant_count)) : "",
  ].filter(Boolean);
  return (
    <button
      type="button"
      data-entity-card={entity.id}
      aria-pressed={selected || undefined}
      onClick={onOpen}
      className={cn(
        "group grid w-full cursor-pointer rounded-lg border-0 bg-transparent p-0 text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring",
        tile ? "gap-2" : "gap-3",
      )}
      data-entity-card-style={tile ? "tile" : "card"}
    >
      <div
        className={cn(
          "relative grid place-items-center overflow-hidden rounded-lg border border-border bg-panel-inset text-muted-foreground transition-colors group-hover:border-border-strong",
          tile ? "aspect-square" : "aspect-[4/5]",
          selected && "border-primary shadow-[0_0_0_1px_var(--primary)] group-hover:border-primary",
        )}
      >
        {entity.cover_asset_id && !broken ? (
          <img
            src={assetThumbnailUrl(entity.cover_asset_id)}
            alt=""
            loading="lazy"
            className="absolute inset-0 h-full w-full object-cover"
            onError={() => setBroken(true)}
          />
        ) : (
          <Icon size={tile ? 24 : 32} strokeWidth={tile ? 1.4 : 1.3} />
        )}
        {entity.tags.length > 0 && (
          <span className="absolute bottom-1.5 left-1.5 flex max-w-[80%] flex-wrap gap-1">
            {entity.tags.slice(0, 3).map((tag) => (
              <span key={tag} className="rounded-sm bg-[rgba(10,12,15,0.7)] px-1.5 py-px text-ui-2xs text-[#e8eaed]">
                {tag}
              </span>
            ))}
          </span>
        )}
      </div>
      {tile ? (
        //: 和参考图卡片下面那一行同一种字号:名字、再是张数。
        <span className="truncate px-0.5 text-ui-xs text-muted-foreground" title={entity.name}>
          <strong className="font-medium text-foreground">{entity.name}</strong>
          {` · ${meta.join(" · ")}`}
        </span>
      ) : (
        <div className="grid min-w-0 gap-1 px-0.5">
          <strong className="truncate text-ui-md font-semibold" title={entity.name}>
            {entity.name}
          </strong>
          <span className="truncate text-ui-xs text-muted-foreground">{meta.join(" · ")}</span>
        </div>
      )}
    </button>
  );
}
