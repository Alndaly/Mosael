import { Trash2 } from "lucide-react";

import type { Asset, Clip, Sequence } from "@/api/client";
import { useI18n } from "@/app/preferences";
import { Button } from "@/components/ui/button";
import { clipEnd, formatTimecode } from "@/domain/timeline/geometry";

export function Inspector({
  sequence,
  selectedClip,
  assets,
  onDeleteClip,
}: {
  sequence: Sequence;
  selectedClip: Clip | null;
  assets: Asset[];
  onDeleteClip: (clipId: string) => void;
}) {
  const t = useI18n();
  const asset = selectedClip ? assets.find((item) => item.id === selectedClip.asset_id) : null;

  return (
    <section className="panel inspector">
      <div className="panel-head">
        <h2>{t("inspector")}</h2>
      </div>
      {selectedClip ? (
        <div className="inspector-body">
          <dl>
            <dt>{t("asset")}</dt>
            <dd className="inspector-ellipsis" title={asset?.name}>{asset?.name ?? selectedClip.asset_id.slice(0, 8)}</dd>
            <dt>{t("timelineRange")}</dt>
            <dd className="timecode">
              {formatTimecode(selectedClip.timeline_start)} – {formatTimecode(clipEnd(selectedClip))}
            </dd>
            <dt>{t("sourceRange")}</dt>
            <dd className="timecode">
              {formatTimecode(selectedClip.src_in)} – {formatTimecode(selectedClip.src_out)}
            </dd>
            <dt>{t("duration")}</dt>
            <dd className="timecode">{formatTimecode(selectedClip.src_out - selectedClip.src_in)}</dd>
            <dt>{t("speed")}</dt>
            <dd className="timecode">{selectedClip.speed.toFixed(2)}x</dd>
            <dt>{t("gain")}</dt>
            <dd className="timecode">{selectedClip.gain.toFixed(2)}</dd>
          </dl>
          <div className="inspector-actions">
            <Button variant="destructive" size="sm" onClick={() => onDeleteClip(selectedClip.id)}>
              <Trash2 size={13} /> {t("deleteClip")}
            </Button>
          </div>
        </div>
      ) : (
        <div className="inspector-body">
          <dl>
            <dt>{t("sequence")}</dt>
            <dd>{sequence.name}</dd>
            <dt>{t("revision")}</dt>
            <dd className="timecode">{sequence.revision}</dd>
            <dt>{t("format")}</dt>
            <dd className="timecode">
              {sequence.width}×{sequence.height} · {sequence.fps}fps
            </dd>
          </dl>
          <p className="inspector-hint">{t("noSelection")}</p>
        </div>
      )}
    </section>
  );
}
