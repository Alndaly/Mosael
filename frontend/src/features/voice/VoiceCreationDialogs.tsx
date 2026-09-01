import React from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { AudioLines, Mic, Square, Upload, X } from "lucide-react";
import { toast } from "sonner";

import {
  api,
  listAssets,
  uploadVoice,
  voiceFromSpeaker,
  type Project,
  type Transcript,
  type Voice,
  type Workspace,
} from "@/api/client";
import { useI18n } from "@/app/preferences";
import { Combobox } from "@/components/app/combobox";
import { DIALOG_FIELD, ModalShell } from "@/components/app/modals";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { formatBytes } from "@/lib/bytes";
import { cn } from "@/lib/utils";
import { useReferenceAudioRecorder } from "./useReferenceAudioRecorder";

type VoiceCreationDialogProps = {
  open: boolean;
  workspace: Workspace;
  onCreated: (voice: Voice) => void;
  onClose: () => void;
};

type UploadVoiceDialogProps = VoiceCreationDialogProps & {
  title?: React.ReactNode;
  submitLabel?: React.ReactNode;
};

/**
 * 上传和直接录制最终都会得到一个参考音频 `File`，因此设置页与剪辑页复用同一个弹窗。
 * 这样权限、空录音、拖放、校验与关闭时释放麦克风不会在两个入口各自漂移。
 */
export function UploadVoiceDialog({
  open,
  workspace,
  onCreated,
  onClose,
  title,
  submitLabel,
}: UploadVoiceDialogProps) {
  const t = useI18n();
  const [name, setName] = React.useState("");
  const [refText, setRefText] = React.useState("");
  const [file, setFile] = React.useState<File | null>(null);
  const [dragOver, setDragOver] = React.useState(false);
  const fileRef = React.useRef<HTMLInputElement | null>(null);
  const formId = React.useId();
  const referenceRecorder = useReferenceAudioRecorder({
    onRecorded: (recorded) => {
      setFile(recorded);
      if (fileRef.current) fileRef.current.value = "";
    },
    onError: (error) =>
      toast.error(t(error === "empty" ? "recordEmpty" : error === "denied" ? "voiceMicDenied" : "recordDenied")),
  });

  const upload = useMutation({
    mutationFn: () => uploadVoice({ workspaceId: workspace.id, name, referenceText: refText, file: file as File }),
    onSuccess: (voice) => {
      referenceRecorder.cancel();
      onCreated(voice);
      onClose();
      toast.success(t("voiceCreated"));
    },
    onError: (error: Error) => toast.error(error.message),
  });

  React.useEffect(() => {
    if (!open) return;
    setName("");
    setRefText("");
    setFile(null);
    setDragOver(false);
    referenceRecorder.cancel();
    if (fileRef.current) fileRef.current.value = "";
    upload.reset();
  }, [open]);

  const close = () => {
    if (upload.isPending) return;
    referenceRecorder.cancel();
    onClose();
  };
  const blocked = !file ? t("voiceNeedRefAudioHere") : !name.trim() ? t("voiceNeedName") : undefined;

  return (
    <ModalShell
      open={open}
      onOpenChange={(nextOpen) => !nextOpen && close()}
      title={title ?? t("voiceUpload")}
      className="sm:max-w-md"
      footer={
        <>
          <Button type="button" size="sm" variant="ghost" disabled={upload.isPending} onClick={close}>
            {t("cancel")}
          </Button>
          <Button
            size="sm"
            type="submit"
            form={formId}
            title={blocked}
            disabled={Boolean(blocked) || referenceRecorder.recording || referenceRecorder.starting}
            loading={upload.isPending}
          >
            {submitLabel ?? t("voiceDoClone")}
          </Button>
        </>
      }
    >
      <form
        id={formId}
        className="grid gap-4"
        onSubmit={(event) => {
          event.preventDefault();
          if (!blocked && !referenceRecorder.recording && !referenceRecorder.starting) upload.mutate();
        }}
      >
        <label className={DIALOG_FIELD}>
          <span>{t("voiceName")}</span>
          <Input value={name} onChange={(event) => setName(event.target.value)} autoFocus />
        </label>
        <label className={DIALOG_FIELD}>
          <span>{t("voiceReferenceTextOptional")}</span>
          <Textarea rows={3} value={refText} onChange={(event) => setRefText(event.target.value)} />
        </label>
        <input
          ref={fileRef}
          type="file"
          accept="audio/*,video/*"
          className="hidden"
          onChange={(event) => setFile(event.target.files?.[0] ?? null)}
        />
        <div
          className={cn(
            "grid gap-2 rounded-lg border border-dashed border-border-strong p-3 transition-colors duration-100",
            dragOver && "border-primary bg-[color-mix(in_oklab,var(--primary)_6%,transparent)]",
          )}
          onDragOver={(event) => {
            event.preventDefault();
            setDragOver(true);
          }}
          onDragLeave={() => setDragOver(false)}
          onDrop={(event) => {
            event.preventDefault();
            setDragOver(false);
            const dropped = event.dataTransfer.files?.[0];
            if (dropped) {
              setFile(dropped);
              if (fileRef.current) fileRef.current.value = "";
            }
          }}
        >
          <div className="flex flex-wrap items-center gap-2">
            <Button
              type="button"
              size="sm"
              variant="outline"
              disabled={referenceRecorder.recording || referenceRecorder.starting}
              onClick={() => fileRef.current?.click()}
            >
              <Upload size={12} /> {file ? t("voiceReplaceFile") : t("voicePickFile")}
            </Button>
            {referenceRecorder.recording ? (
              <Button type="button" size="sm" variant="destructive" onClick={referenceRecorder.stop}>
                <Square size={11} /> {referenceRecorder.seconds}s
              </Button>
            ) : (
              <Button
                type="button"
                size="sm"
                variant="ghost"
                loading={referenceRecorder.starting}
                onClick={() => void referenceRecorder.start()}
              >
                <Mic size={12} /> {t("voiceRecord")}
              </Button>
            )}
          </div>
          {file && !referenceRecorder.recording && (
            <div className="flex min-w-0 items-center gap-1.5 rounded-md border border-border bg-secondary px-2 py-1.5">
              <AudioLines size={12} className="shrink-0 text-muted-foreground" />
              <span className="min-w-0 flex-1 truncate text-ui-xs" title={file.name}>{file.name}</span>
              <span className="shrink-0 text-ui-2xs tabular-nums text-muted-foreground">{formatBytes(file.size)}</span>
              <button
                type="button"
                className="shrink-0 cursor-pointer rounded-sm border-0 bg-transparent p-0.5 leading-none text-muted-foreground hover:text-destructive"
                aria-label={t("voiceClearFile")}
                title={t("voiceClearFile")}
                onClick={() => {
                  setFile(null);
                  if (fileRef.current) fileRef.current.value = "";
                }}
              >
                <X size={12} />
              </button>
            </div>
          )}
          <p className={cn("m-0 text-ui-xs leading-[1.45] text-muted-foreground", blocked && "text-destructive")}>
            {referenceRecorder.recording ? t("voiceRecording") : blocked ?? t("voiceUploadHint")}
          </p>
        </div>
      </form>
    </ModalShell>
  );
}

export function VoiceFromSpeakerDialog({
  open,
  workspace,
  project,
  onCreated,
  onClose,
}: VoiceCreationDialogProps & { project: Project }) {
  const t = useI18n();
  const [assetId, setAssetId] = React.useState("");
  const [speaker, setSpeaker] = React.useState("");
  const [name, setName] = React.useState("");
  const formId = React.useId();
  const assets = useQuery({
    queryKey: ["assets", workspace.id, project.id],
    queryFn: () => listAssets(workspace.id, project.id),
    enabled: open,
  });
  const clipAssets = (assets.data ?? []).filter((asset) => asset.kind === "video" || asset.kind === "audio");
  const transcript = useQuery({
    queryKey: ["transcript", assetId],
    queryFn: () => api<Transcript>(`/api/assets/${assetId}/transcript`),
    enabled: open && Boolean(assetId),
    retry: false,
  });
  const speakers = React.useMemo(
    () => [...new Set((transcript.data?.segments ?? []).map((segment) => segment.speaker).filter((item): item is string => Boolean(item)))],
    [transcript.data],
  );
  const create = useMutation({
    mutationFn: () => voiceFromSpeaker({ asset_id: assetId, speaker: speaker || null, name }),
    onSuccess: (voice) => {
      onCreated(voice);
      onClose();
      toast.success(t("voiceCreated"));
    },
    onError: (error: Error) => toast.error(error.message),
  });

  React.useEffect(() => {
    if (!open) return;
    setAssetId("");
    setSpeaker("");
    setName("");
    create.reset();
  }, [open]);

  const close = () => {
    if (!create.isPending) onClose();
  };

  return (
    <ModalShell
      open={open}
      onOpenChange={(nextOpen) => !nextOpen && close()}
      title={t("voiceFromSpeaker")}
      className="sm:max-w-md"
      footer={
        <>
          <Button type="button" size="sm" variant="ghost" disabled={create.isPending} onClick={close}>
            {t("cancel")}
          </Button>
          <Button
            size="sm"
            type="submit"
            form={formId}
            disabled={!assetId || !speaker}
            loading={create.isPending}
          >
            {t("voiceDoClone")}
          </Button>
        </>
      }
    >
      <form
        id={formId}
        className="grid gap-4"
        onSubmit={(event) => {
          event.preventDefault();
          if (assetId && speaker) create.mutate();
        }}
      >
        <label className={DIALOG_FIELD}>
          <span>{t("voicePickAsset")}</span>
          <Combobox
            value={assetId}
            options={clipAssets.map((asset) => ({ value: asset.id, label: asset.name }))}
            placeholder={t("voicePickAsset")}
            emptyText={t("cmdkEmpty")}
            className="w-full"
            onValueChange={(value) => {
              setAssetId(value);
              setSpeaker("");
            }}
          />
        </label>
        {assetId &&
          (transcript.isError ? (
            <p className="m-0 text-ui-xs leading-[1.45] text-muted-foreground">{t("voiceNoTranscript")}</p>
          ) : speakers.length > 0 ? (
            <label className={DIALOG_FIELD}>
              <span>{t("voicePickSpeaker")}</span>
              <Select value={speaker} onValueChange={setSpeaker}>
                <SelectTrigger aria-label={t("voicePickSpeaker")}>
                  <SelectValue placeholder={t("voicePickSpeaker")} />
                </SelectTrigger>
                <SelectContent>
                  {speakers.map((item) => (
                    <SelectItem key={item} value={item}>{item}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </label>
          ) : transcript.isLoading ? null : (
            <p className="m-0 text-ui-xs leading-[1.45] text-muted-foreground">{t("voiceNoSpeakers")}</p>
          ))}
        <label className={DIALOG_FIELD}>
          <span>{t("voiceName")}</span>
          <Input value={name} onChange={(event) => setName(event.target.value)} />
          <small>{t("voiceFromSpeakerHint")}</small>
        </label>
      </form>
    </ModalShell>
  );
}
