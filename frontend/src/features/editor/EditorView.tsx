import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ImagePlus, Play, Plus, Scissors } from "lucide-react";

import { api, importAsset, type Asset, type Project, type Sequence, type Track, type Workspace } from "@/api/client";
import { useI18n } from "@/app/preferences";
import { Button } from "@/components/ui/button";
import { EmptyState } from "@/components/layout/EmptyState";

export function EditorView({ workspace, project }: { workspace: Workspace; project: Project | null }) {
  const t = useI18n();
  if (!project) {
    return (
      <div className="feature-view">
        <EmptyState icon={<Scissors size={22} />} title={t("emptyProject")} body={t("homeEmptyBody")} />
      </div>
    );
  }
  return <Editor workspace={workspace} project={project} />;
}

function Editor({ workspace, project }: { workspace: Workspace; project: Project }) {
  const t = useI18n();
  const qc = useQueryClient();
  const assets = useQuery({
    queryKey: ["assets", workspace.id, project.id],
    queryFn: () => api<Asset[]>(`/api/assets?workspace_id=${workspace.id}&project_id=${project.id}`),
  });
  const sequences = useQuery({
    queryKey: ["sequences", project.id],
    queryFn: () => api<Sequence[]>(`/api/projects/${project.id}/sequences`),
  });
  const sequence = sequences.data?.[0] ?? null;
  const uploadAsset = useMutation({
    mutationFn: (file: File) => importAsset({ workspaceId: workspace.id, projectId: project.id, file }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["assets", workspace.id, project.id] }),
  });
  const createSequence = useMutation({
    mutationFn: () =>
      api<Sequence>("/api/sequences", {
        method: "POST",
        body: JSON.stringify({ workspace_id: workspace.id, project_id: project.id, name: t("mainSequence") }),
      }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["sequences", project.id] }),
  });
  const insertClip = useMutation({
    mutationFn: ({ asset, track }: { asset: Asset; track: Track }) =>
      api<Sequence>(`/api/sequences/${sequence?.id}/clips`, {
        method: "POST",
        body: JSON.stringify({
          track_id: track.id,
          asset_id: asset.id,
          timeline_start: (track.clips ?? []).reduce((end, clip) => Math.max(end, clip.timeline_start + (clip.src_out - clip.src_in)), 0),
          src_in: 0,
          src_out: Number(asset.media_info.duration ?? 8),
        }),
      }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["sequences", project.id] }),
  });

  const videoTrack = sequence?.tracks?.find((track) => track.kind === "video");

  return (
    <div className="editor-grid">
      <section className="panel media-panel">
        <div className="panel-head">
          <h2>{t("media")}</h2>
          <Button asChild variant="outline" size="sm">
            <label>
              <input
                type="file"
                accept="video/*,audio/*,image/*"
                className="hidden-input"
                onChange={(event) => {
                  const file = event.currentTarget.files?.[0];
                  if (file) uploadAsset.mutate(file);
                  event.currentTarget.value = "";
                }}
              />
              <ImagePlus size={14} /> {t("import")}
            </label>
          </Button>
        </div>
        <div className="asset-list">
          {(assets.data ?? []).map((asset) => (
            <button
              type="button"
              className="asset-row"
              key={asset.id}
              onClick={() => videoTrack && insertClip.mutate({ asset, track: videoTrack })}
              disabled={!videoTrack}
            >
              <span className="asset-kind">{asset.kind}</span>
              <strong>{asset.name}</strong>
              <small className="timecode">{String(asset.media_info.duration ?? "?")}s</small>
            </button>
          ))}
        </div>
      </section>
      <section className="panel monitor">
        <div className="monitor-frame">
          <Play size={42} />
        </div>
      </section>
      <section className="panel inspector">
        <div className="panel-head">
          <h2>{t("inspector")}</h2>
        </div>
        {sequence ? (
          <dl>
            <dt>{t("sequence")}</dt>
            <dd>{sequence.name}</dd>
            <dt>{t("revision")}</dt>
            <dd className="timecode">{sequence.revision}</dd>
            <dt>{t("format")}</dt>
            <dd className="timecode">
              {sequence.width}x{sequence.height} / {sequence.fps}fps
            </dd>
          </dl>
        ) : (
          <div className="inspector-empty">
            <Button onClick={() => createSequence.mutate()}>
              <Plus size={15} /> {t("createMainSequence")}
            </Button>
          </div>
        )}
      </section>
      <section className="panel timeline">
        {sequence ? <Timeline sequence={sequence} /> : <div className="empty-inline">{t("emptyTimeline")}</div>}
      </section>
    </div>
  );
}

function Timeline({ sequence }: { sequence: Sequence }) {
  return (
    <div className="timeline-inner">
      {(sequence.tracks ?? []).map((track) => (
        <div className="track" key={track.id}>
          <div className="track-label">{track.name}</div>
          <div className="track-lane">
            {(track.clips ?? []).map((clip) => (
              <div
                className={`clip clip-${track.kind}`}
                key={clip.id}
                style={{
                  left: `${clip.timeline_start * 20}px`,
                  width: `${Math.max(28, (clip.src_out - clip.src_in) * 20)}px`,
                }}
              >
                {clip.asset_id.slice(0, 6)}
              </div>
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}
