import { Trash2 } from "lucide-react";

import type { Asset, Clip, Sequence } from "@/api/client";
import { useI18n } from "@/app/preferences";
import { Button } from "@/components/ui/button";
import { clipEnd, formatTimecode } from "@/domain/timeline/geometry";

const PIP_POSITIONS: Array<{ key: string; x: number; y: number }> = [
  { key: "↖", x: 0.05, y: 0.06 },
  { key: "↗", x: 0.62, y: 0.06 },
  { key: "↙", x: 0.05, y: 0.6 },
  { key: "↘", x: 0.62, y: 0.6 },
];
const PIP_SIZES = [0.25, 0.33, 0.5];

export function Inspector({
  sequence,
  selectedClip,
  assets,
  isOverlayClip,
  onDeleteClip,
  onSetEffects,
}: {
  sequence: Sequence;
  selectedClip: Clip | null;
  assets: Asset[];
  isOverlayClip: boolean;
  onDeleteClip: (clipId: string) => void;
  onSetEffects: (clipId: string, effects: Record<string, unknown>) => void;
}) {
  const t = useI18n();
  const asset = selectedClip ? assets.find((item) => item.id === selectedClip.asset_id) : null;
  const pip = {
    x: 0.62,
    y: 0.06,
    scale: 0.33,
    ...(((selectedClip?.effects as { pip?: { x?: number; y?: number; scale?: number } })?.pip) ?? {}),
  };
  const applyPip = (patch: Partial<typeof pip>) => {
    if (!selectedClip) return;
    onSetEffects(selectedClip.id, { ...selectedClip.effects, pip: { ...pip, ...patch } });
  };

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
          {isOverlayClip && (
            <div className="pip-controls">
              <span className="pip-label">{t("pipPosition")}</span>
              <div className="pip-row">
                {PIP_POSITIONS.map((position) => (
                  <button
                    key={position.key}
                    type="button"
                    className={
                      Math.abs(pip.x - position.x) < 0.01 && Math.abs(pip.y - position.y) < 0.01
                        ? "pip-btn active"
                        : "pip-btn"
                    }
                    onClick={() => applyPip({ x: position.x, y: position.y })}
                  >
                    {position.key}
                  </button>
                ))}
              </div>
              <span className="pip-label">{t("pipSize")}</span>
              <div className="pip-row">
                {PIP_SIZES.map((size) => (
                  <button
                    key={size}
                    type="button"
                    className={Math.abs(pip.scale - size) < 0.01 ? "pip-btn active" : "pip-btn"}
                    onClick={() => applyPip({ scale: size })}
                  >
                    {Math.round(size * 100)}%
                  </button>
                ))}
              </div>
            </div>
          )}
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
