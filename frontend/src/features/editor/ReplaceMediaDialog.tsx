import React from "react";
import { Film, SearchX } from "lucide-react";

import type { Clip, Sequence } from "@/api/client";
import { useI18n } from "@/app/preferences";
import { AssetGridPicker } from "@/components/app/AssetGridPicker";
import { Button } from "@/components/ui/button";
import { Switch } from "@/components/ui/switch";
import { useAssetSearch } from "@/lib/assetQueries";

//: 哪种轨能换上哪种素材 —— 和后端 sequences/media_swap._ACCEPTS 同一张表(后端也会拒)。
const ACCEPTS: Record<string, readonly string[]> = { video: ["video", "image"], audio: ["audio", "video"] };

/**
 * 片段「替换媒体」:挑一份素材换上去,位置、时长、属性都不动。同一份素材用在好几段时,可以一起换。
 *
 * 候选是这个项目能用的素材(连同工作区级的)里、这条轨放得下的那几种:种类和搜索词交给服务端,往下滚接着取。
 * 挑的样子和别处挑媒体一样(AssetGridPicker 的网格);点一格是选中,换不换由底下的「替换」定 —— 换错了一段
 * 要撤销,先选再确认。
 */
export function ReplaceMediaDialog({
  sequence,
  clipId,
  pending,
  onCancel,
  onReplace,
}: {
  sequence: Sequence;
  clipId: string | null;
  pending?: boolean;
  onCancel: () => void;
  onReplace: (body: { asset_id: string; clip_ids?: string[]; from_asset_id?: string }) => void;
}) {
  const t = useI18n();
  const found = React.useMemo(() => {
    for (const track of sequence.tracks ?? []) {
      const clip = (track.clips ?? []).find((one) => one.id === clipId);
      if (clip) return { clip, track };
    }
    return null;
  }, [sequence, clipId]);
  const [picked, setPicked] = React.useState<string>("");
  const [everywhere, setEverywhere] = React.useState(false);
  React.useEffect(() => {
    setPicked("");
    setEverywhere(false);
  }, [clipId]);
  const clip: Clip | undefined = found?.clip;
  const accepts = ACCEPTS[found?.track.kind ?? ""] ?? [];
  const library = useAssetSearch(
    { workspace_id: sequence.workspace_id, project_id: sequence.project_id, kind: [...accepts] },
    { enabled: Boolean(found) },
  );
  const { search } = library;
  React.useEffect(() => search(""), [clipId, search]);
  const candidates = library.items.filter((asset) => asset.id !== clip?.asset_id);
  const sameAsset = clip?.asset_id
    ? (sequence.tracks ?? []).flatMap((track) => track.clips ?? []).filter((one) => one.asset_id === clip.asset_id).length
    : 0;
  return (
    <AssetGridPicker
      open={Boolean(found)}
      onOpenChange={(open) => !open && !pending && onCancel()}
      title={t("replaceMediaTitle")}
      description={t("replaceMediaHint")}
      searchLabel={t("searchAssets")}
      query={library.text}
      onQueryChange={search}
      banner={
        sameAsset > 1 ? (
          <label className="flex items-center justify-between gap-2 text-ui-sm text-muted-foreground">
            <span>{t("replaceMediaAll").replace("{n}", String(sameAsset))}</span>
            <Switch checked={everywhere} onCheckedChange={setEverywhere} />
          </label>
        ) : null
      }
      items={candidates}
      onActivate={(asset) => setPicked(asset.id)}
      selection={{ isSelected: (asset) => asset.id === picked }}
      mixedKinds={accepts.length > 1}
      pending={library.isPending}
      error={library.isError ? library.error.message : null}
      onRetry={() => void library.refetch()}
      onReachEnd={library.hasNextPage ? () => void (library.isFetchingNextPage || library.fetchNextPage()) : undefined}
      loadingMore={library.isFetchingNextPage}
      empty={
        library.text.trim()
          ? { icon: <SearchX />, title: t("studioNoMatches"), body: t("studioNoMatchesHint") }
          : { icon: <Film />, title: t("replaceMediaNone") }
      }
      footer={
        <>
          <Button variant="outline" onClick={onCancel} disabled={pending}>{t("cancel")}</Button>
          <Button
            disabled={!picked || !clip}
            loading={pending}
            onClick={() =>
              clip &&
              onReplace(
                everywhere && clip.asset_id
                  ? { asset_id: picked, from_asset_id: clip.asset_id }
                  : { asset_id: picked, clip_ids: [clip.id] },
              )
            }
          >
            {t("replaceMediaApply")}
          </Button>
        </>
      }
    />
  );
}
