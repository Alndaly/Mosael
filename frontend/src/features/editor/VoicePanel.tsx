import React from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Loader2, Mic, Play, Square, Trash2, Upload, Wand2 } from "lucide-react";
import { toast } from "sonner";

import {
  api,
  deleteVoice,
  listVoices,
  synthesizeVoice,
  uploadVoice,
  voiceSampleUrl,
  type Job,
  type Project,
  type Workspace,
} from "@/api/client";
import { useI18n } from "@/app/preferences";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";

/** 声音克隆面板:上传参考音频 → 生成音色;选音色 + 输入文本 → 合成配音,
    结果作为音频素材落进素材库,可拖到时间线。 */
export function VoicePanel({
  workspace,
  project,
  tabs,
}: {
  workspace: Workspace;
  project: Project;
  tabs: React.ReactNode;
}) {
  const t = useI18n();
  const qc = useQueryClient();
  const voices = useQuery({ queryKey: ["voices", workspace.id], queryFn: () => listVoices(workspace.id) });
  const [selected, setSelected] = React.useState<string | null>(null);
  const [text, setText] = React.useState("");
  const [uploadOpen, setUploadOpen] = React.useState(false);
  const [name, setName] = React.useState("");
  const [refText, setRefText] = React.useState("");
  const [file, setFile] = React.useState<File | null>(null);
  const fileRef = React.useRef<HTMLInputElement>(null);
  const audioRef = React.useRef<HTMLAudioElement | null>(null);

  const [recording, setRecording] = React.useState(false);
  const [recordSecs, setRecordSecs] = React.useState(0);
  const recorderRef = React.useRef<MediaRecorder | null>(null);
  const timerRef = React.useRef<number | null>(null);

  const stopTimer = () => {
    if (timerRef.current) window.clearInterval(timerRef.current);
    timerRef.current = null;
  };
  const startRecording = async () => {
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const recorder = new MediaRecorder(stream);
      const chunks: Blob[] = [];
      recorder.ondataavailable = (event) => {
        if (event.data.size) chunks.push(event.data);
      };
      recorder.onstop = () => {
        const blob = new Blob(chunks, { type: recorder.mimeType || "audio/webm" });
        setFile(new File([blob], `recording-${Date.now()}.webm`, { type: blob.type }));
        stream.getTracks().forEach((track) => track.stop());
      };
      recorder.start();
      recorderRef.current = recorder;
      setRecording(true);
      setRecordSecs(0);
      timerRef.current = window.setInterval(() => setRecordSecs((s) => s + 1), 1000);
    } catch {
      toast.error(t("voiceMicDenied"));
    }
  };
  const stopRecording = () => {
    recorderRef.current?.stop();
    recorderRef.current = null;
    setRecording(false);
    stopTimer();
  };
  React.useEffect(() => () => stopTimer(), []);

  const list = voices.data ?? [];
  const activeVoice = selected ?? list[0]?.id ?? null;

  const upload = useMutation({
    mutationFn: () => uploadVoice({ workspaceId: workspace.id, name, referenceText: refText, file: file as File }),
    onSuccess: (voice) => {
      void qc.invalidateQueries({ queryKey: ["voices", workspace.id] });
      setUploadOpen(false);
      setName("");
      setRefText("");
      setFile(null);
      setSelected(voice.id);
      toast.success(t("voiceCreated"));
    },
    onError: (error: Error) => toast.error(error.message),
  });
  const remove = useMutation({
    mutationFn: (id: string) => deleteVoice(id),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["voices", workspace.id] }),
  });
  const synth = useMutation({
    mutationFn: () => synthesizeVoice(activeVoice as string, { text, project_id: project.id }),
    onSuccess: (job) => {
      toast.message(t("voiceSynthStarted"));
      setText("");
      pollJob(job.id);
    },
    onError: (error: Error) => toast.error(error.message),
  });

  // The synth Job runs off-thread; when it finishes, refresh the media pool so
  // the generated audio asset shows up (draggable to the timeline).
  const pollJob = (jobId: string) => {
    let ticks = 0;
    const tick = async () => {
      try {
        const job = await api<Job>(`/api/jobs/${jobId}`);
        if (job.status === "succeeded") {
          void qc.invalidateQueries({ queryKey: ["assets", workspace.id, project.id] });
          toast.success(t("voiceSynthDone"));
          return;
        }
        if (job.status === "failed") {
          toast.error(job.error || t("voiceSynthFailed"));
          return;
        }
      } catch {
        /* transient — keep polling */
      }
      if (ticks++ < 200) window.setTimeout(tick, 1500);
    };
    window.setTimeout(tick, 1500);
  };

  const play = (id: string) => {
    if (!audioRef.current) audioRef.current = new Audio();
    audioRef.current.src = voiceSampleUrl(id);
    void audioRef.current.play().catch(() => undefined);
  };

  return (
    <section className="panel media-panel voice-panel">
      <div className="panel-head">{tabs}</div>
      <div className="voice-body">
        <div className="voice-synth">
          <label className="voice-synth-label">
            <Wand2 size={13} /> {t("voiceSynthTitle")}
          </label>
          <Textarea
            className="voice-synth-text"
            placeholder={t("voiceSynthPlaceholder")}
            value={text}
            rows={3}
            onChange={(event) => setText(event.target.value)}
          />
          <Button
            className="voice-synth-go"
            disabled={!activeVoice || !text.trim() || synth.isPending}
            onClick={() => synth.mutate()}
          >
            {synth.isPending ? <Loader2 size={13} className="spin" /> : <Wand2 size={13} />} {t("voiceGenerate")}
          </Button>
          {!activeVoice && <p className="voice-hint">{t("voiceNeedVoice")}</p>}
        </div>

        <div className="voice-list-head">
          <span>{t("voiceLibrary")}</span>
          <Button size="sm" variant="outline" onClick={() => setUploadOpen((open) => !open)}>
            <Upload size={12} /> {t("voiceUpload")}
          </Button>
        </div>

        {uploadOpen && (
          <div className="voice-upload">
            <Input placeholder={t("voiceName")} value={name} onChange={(event) => setName(event.target.value)} />
            <Textarea
              placeholder={t("voiceRefText")}
              value={refText}
              rows={2}
              onChange={(event) => setRefText(event.target.value)}
            />
            <input
              ref={fileRef}
              type="file"
              accept="audio/*,video/*"
              className="hidden-input"
              onChange={(event) => setFile(event.target.files?.[0] ?? null)}
            />
            <div className="voice-upload-actions">
              <div className="voice-upload-source">
                <Button size="sm" variant="ghost" disabled={recording} onClick={() => fileRef.current?.click()}>
                  {file && !recording ? file.name.slice(0, 18) : t("voicePickFile")}
                </Button>
                {recording ? (
                  <Button size="sm" variant="destructive" onClick={stopRecording}>
                    <Square size={11} /> {recordSecs}s
                  </Button>
                ) : (
                  <Button size="sm" variant="ghost" onClick={startRecording}>
                    <Mic size={12} /> {t("voiceRecord")}
                  </Button>
                )}
              </div>
              <Button
                size="sm"
                disabled={!name.trim() || !file || recording || upload.isPending}
                onClick={() => upload.mutate()}
              >
                {upload.isPending ? <Loader2 size={12} className="spin" /> : null} {t("confirm")}
              </Button>
            </div>
            <p className="voice-hint">{recording ? t("voiceRecording") : t("voiceUploadHint")}</p>
          </div>
        )}

        <div className="voice-list">
          {list.map((voice) => (
            <div
              key={voice.id}
              className={voice.id === activeVoice ? "voice-item active" : "voice-item"}
              role="button"
              tabIndex={0}
              onClick={() => setSelected(voice.id)}
            >
              <div className="voice-item-main">
                <Mic size={13} />
                <div className="voice-item-text">
                  <strong>{voice.name}</strong>
                  {voice.reference_text && <small>{voice.reference_text}</small>}
                </div>
              </div>
              <div className="voice-item-actions">
                <button
                  type="button"
                  title={t("voicePlay")}
                  onClick={(event) => {
                    event.stopPropagation();
                    play(voice.id);
                  }}
                >
                  <Play size={12} />
                </button>
                <button
                  type="button"
                  title={t("delete")}
                  onClick={(event) => {
                    event.stopPropagation();
                    remove.mutate(voice.id);
                  }}
                >
                  <Trash2 size={12} />
                </button>
              </div>
            </div>
          ))}
          {list.length === 0 && !voices.isLoading && <p className="voice-empty">{t("voiceEmpty")}</p>}
        </div>
      </div>
    </section>
  );
}
