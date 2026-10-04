import React from "react";

import type { Asset, Clip, Sequence } from "@/api/client";
import { useI18n } from "@/app/preferences";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Switch } from "@/components/ui/switch";
import { Truncate } from "@/components/ui/truncate";
import { cn } from "@/lib/utils";

//: 哪种轨能换上哪种素材 —— 和后端 sequences/media_swap._ACCEPTS 同一张表(后端也会拒)。
const ACCEPTS: Record<string, readonly string[]> = { video: ["video", "image"], audio: ["audio", "video"] };

/**
 * 片段「替换媒体」:挑一份素材换上去,位置、时长、属性都不动。同一份素材用在好几段时,可以一起换。
 */
export function ReplaceMediaDialog({
  sequence,
  clipId,
  assets,
  pending,
  onCancel,
  onReplace,
}: {
  sequence: Sequence;
  clipId: string | null;
  assets: readonly Asset[];
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
  const candidates = assets.filter((asset) => accepts.includes(asset.kind) && asset.id !== clip?.asset_id);
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
        {candidates.length === 0 ? (
          <p className="text-ui-sm text-muted-foreground">{t("replaceMediaNone")}</p>
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
