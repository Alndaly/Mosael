import { useQuery } from "@tanstack/react-query";

import { getAssetLineage, type AssetLineageNode } from "@/api/client";
import { assetKeys } from "@/api/queryKeys";
import type { MessageKey } from "@/app/messages";
import { useI18n } from "@/app/preferences";
import { Truncate } from "@/components/ui/truncate";

/** 派生操作 → 文案。和后端 domain/assets/lineage.OPS 是同一张封闭的表;认不得的照原样显示。 */
const OP_LABELS: Record<string, MessageKey> = {
  trim: "assetLineageOpTrim",
  frame: "assetLineageOpFrame",
  grid_split: "assetLineageOpGridSplit",
  gif: "assetLineageOpGif",
  denoise: "assetLineageOpDenoise",
  separate: "assetLineageOpSeparate",
  export: "assetLineageOpExport",
  concat: "assetLineageOpConcat",
  pad: "assetLineageOpPad",
  mix: "assetLineageOpMix",
  extract: "assetLineageOpExtract",
  plugin: "assetLineageOpPlugin",
};

/**
 * 素材详情里的「来自」:这份素材是从哪几份、经过什么操作做出来的 —— 「xxx(截取)」,点一下看那一份。
 * 出处自己还有出处的,缩进一级接着往下列(后端最多交回几级)。出处已经被删的写「已删除的素材」,不能点。
 */
export function AssetLineageList({ assetId, onOpen }: { assetId: string; onOpen: (assetId: string) => void }) {
  const t = useI18n();
  const lineage = useQuery({ queryKey: assetKeys.lineage(assetId), queryFn: () => getAssetLineage(assetId) });
  if (lineage.isPending) return <span className="text-muted-foreground">{t("pageLoading")}</span>;
  if (!lineage.data?.parents.length) return <span className="text-muted-foreground">—</span>;
  return <LineageNodes nodes={lineage.data.parents} onOpen={onOpen} />;
}

function LineageNodes({ nodes, onOpen }: { nodes: AssetLineageNode[]; onOpen: (assetId: string) => void }) {
  const t = useI18n();
  return (
    <ul className="m-0 grid list-none gap-1 p-0" data-asset-lineage="">
      {nodes.map((node) => {
        const op = OP_LABELS[node.op];
        return (
          <li key={`${node.asset_id}:${node.op}`} className="grid min-w-0 gap-1">
            <span className="inline-flex min-w-0 max-w-full items-baseline gap-1">
              {node.name == null ? (
                <Truncate className="text-muted-foreground">{t("assetLineageDeleted")}</Truncate>
              ) : (
                <button
                  type="button"
                  className="min-w-0 cursor-pointer border-0 bg-transparent p-0 text-left text-ui-sm text-foreground hover:text-primary"
                  onClick={() => onOpen(node.asset_id)}
                >
                  <Truncate>{node.name}</Truncate>
                </button>
              )}
              <span className="shrink-0 text-ui-xs text-muted-foreground">({op ? t(op) : node.op})</span>
            </span>
            {node.parents && node.parents.length > 0 && (
              <div className="border-l border-divider pl-2">
                <LineageNodes nodes={node.parents} onOpen={onOpen} />
              </div>
            )}
          </li>
        );
      })}
    </ul>
  );
}
