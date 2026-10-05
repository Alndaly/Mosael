import React from "react";

import { Search } from "lucide-react";

import type { Clip, Sequence } from "@/api/client";
import { useI18n } from "@/app/preferences";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Switch } from "@/components/ui/switch";
import { Truncate } from "@/components/ui/truncate";
import { useAssetSearch } from "@/lib/assetQueries";
import { useReachEnd } from "@/lib/useReachEnd";
import { cn } from "@/lib/utils";

//: 哪种轨能换上哪种素材 —— 和后端 sequences/media_swap._ACCEPTS 同一张表(后端也会拒)。
const ACCEPTS: Record<string, readonly string[]> = { video: ["video", "image"], audio: ["audio", "video"] };

/**
 * 片段「替换媒体」:挑一份素材换上去,位置、时长、属性都不动。同一份素材用在好几段时,可以一起换。
 *
 * 候选是这个项目能用的素材(连同工作区级的)里、这条轨放得下的那几种:种类和搜索词交给服务端,往下滚接着取。
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
  const end = useReachEnd<HTMLLIElement>(
    library.hasNextPage ? () => void (library.isFetchingNextPage || library.fetchNextPage()) : undefined,
    candidates.length,
  );
  const sameAsset = clip?.asset_id
    ? (sequence.tracks ?? []).flatMap((track) => track.clips ?? []).filter((one) => one.asset_id === clip.asset_id).length
    : 0;
  return (
    <Dialog open={Boolean(found)} onOpenChange={(open) => !open && !pending && onCancel()}>
      <DialogContent className="max-w-md">
        <DialogHeader>
          <DialogTitle>{t("replaceMediaTitle")}</DialogTitle>
          <DialogDescription>{t("replaceMediaHint")}</DialogDescription>
        </DialogHeader>
        <div className="relative">
          <Search size={14} className="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-muted-foreground" />
          <Input
            size="sm"
            className="pl-8"
            aria-label={t("searchAssets")}
            placeholder={t("searchAssets")}
            value={library.text}
            onChange={(event) => search(event.currentTarget.value)}
          />
        </div>
        {library.isPending ? (
          <p className="text-ui-sm text-muted-foreground">{t("pageLoading")}</p>
        ) : candidates.length === 0 ? (
          <p className="text-ui-sm text-muted-foreground">{t(library.query ? "studioNoMatches" : "replaceMediaNone")}</p>
        ) : (
          <ul role="listbox" aria-label={t("replaceMediaTitle")} className="m-0 grid max-h-64 list-none gap-1 overflow-y-auto p-0">
            {candidates.map((asset) => (
              <li key={asset.id}>
                <button
                  type="button"
                  role="option"
                  aria-selected={picked === asset.id}
                  className={cn(
                    "w-full rounded-md border border-transparent px-2 py-1.5 text-left text-ui-sm hover:bg-secondary",
                    picked === asset.id && "border-primary bg-[color-mix(in_oklab,var(--primary)_10%,transparent)]",
                  )}
                  onClick={() => setPicked(asset.id)}
                >
                  <Truncate>{asset.name}</Truncate>
                </button>
              </li>
            ))}
            {library.hasNextPage && <li ref={end} aria-hidden="true" className="h-px" />}
          </ul>
        )}
        {sameAsset > 1 && (
          <label className="flex items-center justify-between gap-2 text-ui-xs text-muted-foreground">
            <span>{t("replaceMediaAll").replace("{n}", String(sameAsset))}</span>
            <Switch checked={everywhere} onCheckedChange={setEverywhere} />
          </label>
        )}
        <DialogFooter>
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
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
