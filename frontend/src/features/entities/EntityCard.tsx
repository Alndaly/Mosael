import React from "react";

import { assetThumbnailUrl, type EntitySummary } from "@/api/client";
import { useI18n } from "@/app/preferences";
import { entityKindIcon } from "@/features/entities/entityMeta";

/** 一张封面卡:封面、名字、参考图和变体的张数、标签。没有封面时是种类的图标。 */
export function EntityCard({ entity, onOpen }: { entity: EntitySummary; onOpen: () => void }) {
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
      onClick={onOpen}
      className="group grid cursor-pointer gap-3 rounded-lg border-0 bg-transparent p-0 text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
    >
      <div className="relative grid aspect-[4/5] place-items-center overflow-hidden rounded-lg border border-border bg-panel-inset text-muted-foreground transition-colors group-hover:border-border-strong">
        {entity.cover_asset_id && !broken ? (
          <img
            src={assetThumbnailUrl(entity.cover_asset_id)}
            alt=""
            loading="lazy"
            className="absolute inset-0 h-full w-full object-cover"
            onError={() => setBroken(true)}
          />
        ) : (
          <Icon size={32} strokeWidth={1.3} />
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
      <div className="grid min-w-0 gap-1 px-0.5">
        <strong className="truncate text-ui-md font-semibold" title={entity.name}>
          {entity.name}
        </strong>
        <span className="truncate text-ui-xs text-muted-foreground">{meta.join(" · ")}</span>
      </div>
    </button>
  );
}
