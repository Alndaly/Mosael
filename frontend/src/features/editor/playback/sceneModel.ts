import type { Asset, Clip, Track } from "@/api/client";
import { clipEnd } from "@/domain/timeline/geometry";

/**
 * The visible video/image layers at a given time, bottom→top — the single deterministic authority
 * for "what is on screen at t" on the preview side. Pure: no React, no stores, no decoding.
 *
 * The export side has an equivalent implementation in `backend/app/media/scene.py`. Two
 * implementations are unavoidable: preview must evaluate locally at 60fps over uncommitted drag
 * drafts, export must stay headless, backend-side and claimable by an external worker (ADR-0002).
 * They are kept honest by `contracts/scene-cases.json`, a language-neutral corpus both test suites
 * run (see sceneModel.parity.test.ts) — so a semantic change on one side alone turns both red.
 *
 * Z-order follows PR/DaVinci and Monitor's DOM order: video tracks sorted by position ascending
 * (top row first), so the bottom-most track is the BASE (full-frame, follows fill mode) and tracks
 * above it composite upward. Text/subtitle clips (no asset) are a separate layer and excluded here.
 */
export interface SceneLayer {
  clip: Clip;
  asset: Asset;
  /** Which track it came from — carried so the contract can pin z-order, not just clip identity. */
  trackId: string;
  /** The base track's active clip: framed by the sequence fill mode. Overlays always cover. */
  isBase: boolean;
}

function isVisualClip(clip: Clip, assetById: Map<string, Asset>): boolean {
  if (!clip.asset_id) return false; // text/花字 overlays are drawn elsewhere
  const asset = assetById.get(clip.asset_id);
  return !!asset && (asset.kind === "video" || asset.kind === "image");
}

function videoTracksSorted(tracks: Track[]): Track[] {
  return tracks.filter((tr) => tr.kind === "video").sort((a, b) => a.position - b.position);
}

/** Video tracks that actually carry picture, ascending (top row first). A track holding only text
    clips is not one of them — treating it as picture would make it a base with no media. */
function videoTracksWithMedia(tracks: Track[], assetById: Map<string, Asset>): Track[] {
  return videoTracksSorted(tracks).filter((tr) => (tr.clips ?? []).some((c) => isVisualClip(c, assetById)));
}

function activeClipOnTrack(track: Track, assetById: Map<string, Asset>, t: number): { clip: Clip; asset: Asset } | null {
  // Clips on one track never overlap, so at most one is active; sort so a well-formed timeline is
  // deterministic even if clips arrive unordered. Half-open [start, end): at a cut only the later
  // clip matches, so the switch frame draws exactly one layer.
  for (const clip of [...(track.clips ?? [])].sort((a, b) => a.timeline_start - b.timeline_start)) {
    if (!isVisualClip(clip, assetById)) continue;
    if (!(t >= clip.timeline_start && t < clipEnd(clip))) continue;
    return { clip, asset: assetById.get(clip.asset_id!)! };
  }
  return null;
}

export function sceneLayersAt(tracks: Track[], assetById: Map<string, Asset>, t: number): SceneLayer[] {
  // A muted video track still shows its picture: the track header's mute is a speaker icon and means
  // audio only (audio honours it in WebAudioMixer). Hiding the picture would make muting a PiP track
  // delete that layer from the render.
  const withMedia = videoTracksWithMedia(tracks, assetById);
  if (withMedia.length === 0) return [];
  const layers: SceneLayer[] = [];
  // Base = the bottom-most track that actually HAS picture. Taking the literal bottom-most track
  // instead would demote the real picture to an overlay whenever an empty track sits below it —
  // silently dropping the sequence fill mode (contain/blur) that only the base honours.
  const baseTrack = withMedia[withMedia.length - 1];
  const base = activeClipOnTrack(baseTrack, assetById, t);
  if (base) layers.push({ ...base, trackId: baseTrack.id, isBase: true });
  // ...then overlays bottom→top: every picture track above the base, from just-above-base upward.
  for (const track of withMedia.slice(0, -1).reverse()) {
    const active = activeClipOnTrack(track, assetById, t);
    if (active) layers.push({ ...active, trackId: track.id, isBase: false });
  }
  return layers;
}
