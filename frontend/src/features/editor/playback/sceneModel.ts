import type { Asset, Clip, Track } from "@/api/client";
import { clipEnd } from "@/domain/timeline/geometry";

/**
 * The visible video/image layers at a given time, bottom→top — the single deterministic authority
 * for "what is on screen at t". Both the live preview compositor and the offline export renderer
 * consume this, so the two can never disagree about which clips composite or in what order (the
 * root cause of the preview↔export parity bugs). Pure: no React, no stores, no decoding.
 *
 * Z-order follows PR/DaVinci and Monitor's DOM order: video tracks sorted by position ascending
 * (top row first), so the bottom-most track is the BASE (full-frame, follows fill mode) and tracks
 * above it composite upward. Text/subtitle clips (no asset) are a separate layer and excluded here.
 */
export interface SceneLayer {
  clip: Clip;
  asset: Asset;
  /** The bottom-most video track's active clip: framed by the sequence fill mode. Overlays cover. */
  isBase: boolean;
}

function activeClipOnTrack(track: Track, assetById: Map<string, Asset>, t: number): { clip: Clip; asset: Asset } | null {
  // Clips on one track never overlap, so at most one is active; sort so a well-formed timeline is
  // deterministic even if clips arrive unordered.
  for (const clip of [...(track.clips ?? [])].sort((a, b) => a.timeline_start - b.timeline_start)) {
    if (!clip.asset_id) continue; // text/花字 overlays are drawn elsewhere
    if (!(t >= clip.timeline_start && t < clipEnd(clip))) continue;
    const asset = assetById.get(clip.asset_id);
    if (!asset || (asset.kind !== "video" && asset.kind !== "image")) continue;
    return { clip, asset };
  }
  return null;
}

export function sceneLayersAt(tracks: Track[], assetById: Map<string, Asset>, t: number): SceneLayer[] {
  // Note: a muted video track still shows its picture (muting affects audio only) — matching the
  // preview compositor, whose base/overlay layer lists don't filter on track.muted either.
  const videoTracks = tracks.filter((tr) => tr.kind === "video").sort((a, b) => a.position - b.position);
  if (videoTracks.length === 0) return [];
  const layers: SceneLayer[] = [];
  // Base first (bottom-most track = last after ascending sort)...
  const base = activeClipOnTrack(videoTracks[videoTracks.length - 1], assetById, t);
  if (base) layers.push({ ...base, isBase: true });
  // ...then overlays bottom→top: every track above the base, from just-above-base up to the top.
  for (const track of videoTracks.slice(0, -1).reverse()) {
    const active = activeClipOnTrack(track, assetById, t);
    if (active) layers.push({ ...active, isBase: false });
  }
  return layers;
}
