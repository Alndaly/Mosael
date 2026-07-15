import React from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Plus, Scissors } from "lucide-react";

import {
  api,
  deleteClip,
  importAsset,
  insertClip,
  moveClip,
  trimClip,
  type Asset,
  type Project,
  type Sequence,
  type Workspace,
} from "@/api/client";
import { useI18n } from "@/app/preferences";
import { Button } from "@/components/ui/button";
import { EmptyState } from "@/components/layout/EmptyState";
import { clipEnd } from "@/domain/timeline/geometry";
import { useEditorStore } from "@/stores/editorStore";
import { Inspector } from "./Inspector";
import { MediaPool } from "./MediaPool";
import { Monitor } from "./Monitor";
import { Timeline, trackAcceptsAsset, type TrimPayload } from "./timeline/Timeline";

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
  const selectedClipId = useEditorStore((state) => state.selectedClipId);

  const assets = useQuery({
    queryKey: ["assets", workspace.id, project.id],
    queryFn: () => api<Asset[]>(`/api/assets?workspace_id=${workspace.id}&project_id=${project.id}`),
  });
  const sequences = useQuery({
    queryKey: ["sequences", project.id],
    queryFn: () => api<Sequence[]>(`/api/projects/${project.id}/sequences`),
  });
  const sequence = sequences.data?.[0] ?? null;

  const refreshSequences = () => qc.invalidateQueries({ queryKey: ["sequences", project.id] });
  const settleDraft = async () => {
    await refreshSequences();
    useEditorStore.getState().setDragDraft(null);
  };

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
    onSuccess: refreshSequences,
  });
  const insertClipMutation = useMutation({
    mutationFn: (args: { trackId: string; assetId: string; timelineStart: number; srcIn: number; srcOut: number }) =>
      insertClip(sequence!.id, {
        track_id: args.trackId,
        asset_id: args.assetId,
        timeline_start: args.timelineStart,
        src_in: args.srcIn,
        src_out: args.srcOut,
      }),
    onSuccess: refreshSequences,
  });
  const moveClipMutation = useMutation({
    mutationFn: ({ clipId, timelineStart }: { clipId: string; timelineStart: number }) =>
      moveClip(sequence!.id, clipId, { timeline_start: timelineStart }),
    onSettled: settleDraft,
  });
  const trimClipMutation = useMutation({
    mutationFn: ({ clipId, payload }: { clipId: string; payload: TrimPayload }) =>
      trimClip(sequence!.id, clipId, payload),
    onSettled: settleDraft,
  });
  const deleteClipMutation = useMutation({
    mutationFn: (clipId: string) => deleteClip(sequence!.id, clipId),
    onSuccess: () => {
      useEditorStore.getState().selectClip(null);
      void refreshSequences();
    },
  });

  const allClips = React.useMemo(
    () => (sequence?.tracks ?? []).flatMap((track) => track.clips ?? []),
    [sequence],
  );
  const selectedClip = allClips.find((clip) => clip.id === selectedClipId) ?? null;

  const addAssetToTimeline = (asset: Asset) => {
    if (!sequence) return;
    const track = (sequence.tracks ?? []).find((item) => trackAcceptsAsset(item, asset));
    if (!track) return;
    const trackEnd = (track.clips ?? []).reduce((end, clip) => Math.max(end, clipEnd(clip)), 0);
    const duration = typeof asset.media_info.duration === "number" ? asset.media_info.duration : 5;
    insertClipMutation.mutate({
      trackId: track.id,
      assetId: asset.id,
      timelineStart: trackEnd,
      srcIn: 0,
      srcOut: duration,
    });
  };

  // Keyboard: space toggles playback, delete removes selection.
  React.useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null;
      if (target && (target.tagName === "INPUT" || target.tagName === "TEXTAREA" || target.isContentEditable)) return;
      if (event.code === "Space") {
        event.preventDefault();
        useEditorStore.getState().togglePlaying();
      } else if (event.key === "Delete" || event.key === "Backspace") {
        const clipId = useEditorStore.getState().selectedClipId;
        if (clipId && sequence) {
          event.preventDefault();
          deleteClipMutation.mutate(clipId);
        }
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sequence?.id]);

  if (!sequence) {
    return (
      <div className="feature-view">
        <EmptyState
          icon={<Scissors size={22} />}
          title={t("emptyTimeline")}
          body={t("mediaEmptyBody")}
          action={
            <Button onClick={() => createSequence.mutate()} disabled={createSequence.isPending}>
              <Plus size={15} /> {t("createMainSequence")}
            </Button>
          }
        />
      </div>
    );
  }

  return (
    <div className="editor-grid">
      <MediaPool
        assets={assets.data ?? []}
        uploading={uploadAsset.isPending}
        onImportFile={(file) => uploadAsset.mutate(file)}
        onAddToTimeline={addAssetToTimeline}
      />
      <section className="panel monitor">
        <Monitor sequence={sequence} assets={assets.data ?? []} />
      </section>
      <Inspector
        sequence={sequence}
        selectedClip={selectedClip}
        assets={assets.data ?? []}
        onDeleteClip={(clipId) => deleteClipMutation.mutate(clipId)}
      />
      <section className="panel timeline">
        <Timeline
          sequence={sequence}
          assets={assets.data ?? []}
          onInsertClip={(args) => insertClipMutation.mutate(args)}
          onMoveClip={(clipId, timelineStart) => moveClipMutation.mutate({ clipId, timelineStart })}
          onTrimClip={(clipId, payload) => trimClipMutation.mutate({ clipId, payload })}
        />
      </section>
    </div>
  );
}
