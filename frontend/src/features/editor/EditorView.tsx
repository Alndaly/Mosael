import React from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CircleAlert, CircleCheck, Download, Loader2, Plus, Redo2, Scissors, Undo2 } from "lucide-react";

import {
  api,
  deleteClip,
  exportSequence,
  importAsset,
  insertClip,
  moveClip,
  redoSequence,
  trimClip,
  undoSequence,
  type Asset,
  type Job,
  type Project,
  type Sequence,
  type Workspace,
} from "@/api/client";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
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
  const undoMutation = useMutation({
    mutationFn: () => undoSequence(sequence!.id),
    onSuccess: () => {
      useEditorStore.getState().selectClip(null);
      void refreshSequences();
    },
  });
  const redoMutation = useMutation({
    mutationFn: () => redoSequence(sequence!.id),
    onSuccess: refreshSequences,
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
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "z") {
        event.preventDefault();
        if (event.shiftKey) redoMutation.mutate();
        else undoMutation.mutate();
      } else if (event.code === "Space") {
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
          toolbarExtra={
            <>
              <Tooltip>
                <TooltipTrigger asChild>
                  <Button
                    variant="ghost"
                    size="icon-sm"
                    disabled={!sequence.can_undo || undoMutation.isPending}
                    onClick={() => undoMutation.mutate()}
                    aria-label={t("undo")}
                  >
                    <Undo2 size={14} />
                  </Button>
                </TooltipTrigger>
                <TooltipContent>{t("undo")} (⌘Z)</TooltipContent>
              </Tooltip>
              <Tooltip>
                <TooltipTrigger asChild>
                  <Button
                    variant="ghost"
                    size="icon-sm"
                    disabled={!sequence.can_redo || redoMutation.isPending}
                    onClick={() => redoMutation.mutate()}
                    aria-label={t("redoAction")}
                  >
                    <Redo2 size={14} />
                  </Button>
                </TooltipTrigger>
                <TooltipContent>{t("redoAction")} (⇧⌘Z)</TooltipContent>
              </Tooltip>
              <ExportControl workspaceId={workspace.id} projectId={project.id} sequenceId={sequence.id} />
            </>
          }
        />
      </section>
    </div>
  );
}

function ExportControl({
  workspaceId,
  projectId,
  sequenceId,
}: {
  workspaceId: string;
  projectId: string;
  sequenceId: string;
}) {
  const t = useI18n();
  const qc = useQueryClient();
  const [jobId, setJobId] = React.useState<string | null>(null);
  const startExport = useMutation({
    mutationFn: () => exportSequence(sequenceId),
    onSuccess: (job) => setJobId(job.id),
  });
  const job = useQuery({
    queryKey: ["job", jobId],
    enabled: Boolean(jobId),
    queryFn: () => api<Job>(`/api/jobs/${jobId}`),
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      return status === "succeeded" || status === "failed" ? false : 700;
    },
    refetchIntervalInBackground: true,
  });

  const status = jobId ? (job.data?.status ?? "queued") : null;
  React.useEffect(() => {
    if (status === "succeeded") {
      void qc.invalidateQueries({ queryKey: ["assets", workspaceId, projectId] });
      void qc.invalidateQueries({ queryKey: ["assets", workspaceId] });
    }
  }, [status, qc, workspaceId, projectId]);

  const busy = startExport.isPending || status === "queued" || status === "running";

  return (
    <span className="export-control">
      {status === "running" && (
        <span className="export-status timecode">{Math.round((job.data?.progress ?? 0) * 100)}%</span>
      )}
      {status === "succeeded" && (
        <span className="export-status done">
          <CircleCheck size={13} /> {t("exportDone")}
        </span>
      )}
      {status === "failed" && (
        <span className="export-status failed" title={job.data?.error ?? undefined}>
          <CircleAlert size={13} /> {t("exportFailed")}
        </span>
      )}
      <Button size="sm" variant="outline" disabled={busy} onClick={() => startExport.mutate()}>
        {busy ? <Loader2 size={13} className="spin" /> : <Download size={13} />}
        {busy ? t("exporting") : t("exportVideo")}
      </Button>
    </span>
  );
}
