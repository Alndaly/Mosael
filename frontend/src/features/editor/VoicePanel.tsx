import React from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Loader2, Mic, Play, Square, Trash2, Upload, UsersRound, Wand2 } from "lucide-react";
import { toast } from "sonner";

import {
  api,
  deleteVoice,
  listAssets,
  listTtsEngines,
  listTtsVoices,
  listVoices,
  synthesizeVoice,
  synthesizeWithEngine,
  uploadVoice,
  voiceFromSpeaker,
  voiceSampleUrl,
  type Job,
  type Project,
  type Transcript,
  type Workspace,
} from "@/api/client";
import { useI18n } from "@/app/preferences";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
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
  // Which engine synthesises. "clone" is the local reference-driven path and needs a Voice row;
  // every other engine is remote and supplies its own voice, so the two submit to different
  // endpoints — see the synth mutation below.
  const [engine, setEngine] = React.useState("clone");
  const [engineVoice, setEngineVoice] = React.useState("");
  const engines = useQuery({ queryKey: ["tts-engines"], queryFn: listTtsEngines, staleTime: Infinity });
  const activeEngine = engines.data?.find((item) => item.id === engine);
  // Fetched per engine rather than bundled with the engine list: 火山's catalogue depends on
  // the account, so it is a live lookup that can change without the engine list changing.
  const engineVoices = useQuery({
    queryKey: ["tts-voices", engine],
    queryFn: () => listTtsVoices(engine),
    enabled: engine !== "clone",
  });
  const voiceChoices = engineVoices.data ?? [];
  const chosenVoice = voiceChoices.find((item) => item.value === engineVoice);
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
    mutationFn: () =>
      engine === "clone"
        ? synthesizeVoice(activeVoice as string, { text, project_id: project.id })
        : synthesizeWithEngine({
            workspace_id: workspace.id,
            text,
            engine,
            engine_voice: engineVoice,
            // The family only the listing knows; without it 火山 answers 55000000.
            engine_voice_resource: chosenVoice?.resource_id ?? "",
            project_id: project.id,
          }),
    onSuccess: (job) => {
      toast.message(t("voiceSynthStarted"));
      setText("");
      pollJob(job.id);
    },
    onError: (error: Error) => toast.error(error.message),
  });

  // Clone needs a voice from the library; a remote engine needs a voice id only when its
  // catalogue is too account-specific to enumerate.
  const engineReady =
    engine === "clone"
      ? Boolean(activeVoice)
      : voiceChoices.length > 0 || !activeEngine?.needs_voice_id || Boolean(engineVoice.trim());

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

  // Clone from a transcribed speaker: pick a transcribed asset → its speaker.
  const [speakerOpen, setSpeakerOpen] = React.useState(false);
  const [spAsset, setSpAsset] = React.useState("");
  const [spSpeaker, setSpSpeaker] = React.useState("");
  const [spName, setSpName] = React.useState("");
  const assets = useQuery({
    queryKey: ["assets", workspace.id, project.id],
    queryFn: () => listAssets(workspace.id, project.id),
    enabled: speakerOpen,
  });
  const clipAssets = (assets.data ?? []).filter((asset) => asset.kind === "video" || asset.kind === "audio");
  const transcript = useQuery({
    queryKey: ["transcript", spAsset],
    queryFn: () => api<Transcript>(`/api/assets/${spAsset}/transcript`),
    enabled: speakerOpen && Boolean(spAsset),
    retry: false,
  });
  const speakers = React.useMemo(
    () => [...new Set((transcript.data?.segments ?? []).map((seg) => seg.speaker).filter((s): s is string => !!s))],
    [transcript.data],
  );
  const fromSpeaker = useMutation({
    mutationFn: () => voiceFromSpeaker({ asset_id: spAsset, speaker: spSpeaker || null, name: spName }),
    onSuccess: (voice) => {
      void qc.invalidateQueries({ queryKey: ["voices", workspace.id] });
      setSpeakerOpen(false);
      setSpAsset("");
      setSpSpeaker("");
      setSpName("");
      setSelected(voice.id);
      toast.success(t("voiceCreated"));
    },
    onError: (error: Error) => toast.error(error.message),
  });

  return (
    <section className="panel media-panel voice-panel">
      <div className="panel-head">{tabs}</div>
      <div className="voice-body">
        <div className="voice-synth">
          <label className="voice-synth-label">
            <Wand2 size={13} /> {t("voiceSynthTitle")}
          </label>
          <div className="voice-synth-engine">
            <Select
              value={engine}
              onValueChange={(value) => {
                setEngine(value);
                // Voice ids do not carry across engines — "alloy" means nothing to 火山 — and
                // the new engine's list arrives asynchronously, so clear rather than guess.
                setEngineVoice("");
              }}
            >
              <SelectTrigger className="voice-synth-select" aria-label={t("voiceEngine")}>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {(engines.data ?? []).map((item) => (
                  <SelectItem key={item.id} value={item.id}>
                    {item.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            {engine !== "clone" && voiceChoices.length > 0 && (
              <Select value={engineVoice || voiceChoices[0].value} onValueChange={setEngineVoice}>
                <SelectTrigger className="voice-synth-select" aria-label={t("voiceEngineVoice")}>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {voiceChoices.map((voice) => (
                    <SelectItem key={voice.value} value={voice.value}>
                      {voice.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            )}
            {activeEngine?.needs_voice_id && voiceChoices.length === 0 && (
              <Input
                className="voice-synth-select"
                value={engineVoice}
                placeholder={t("voiceEngineVoiceIdHint")}
                aria-label={t("voiceEngineVoiceId")}
                onChange={(event) => setEngineVoice(event.target.value)}
              />
            )}
          </div>
          <Textarea
            className="voice-synth-text"
            placeholder={t("voiceSynthPlaceholder")}
            value={text}
            rows={3}
            onChange={(event) => setText(event.target.value)}
          />
          <Button
            className="voice-synth-go"
            disabled={!text.trim() || synth.isPending || !engineReady}
            onClick={() => synth.mutate()}
          >
            {synth.isPending ? <Loader2 size={13} className="spin" /> : <Wand2 size={13} />} {t("voiceGenerate")}
          </Button>
          {engine === "clone" && !activeVoice && <p className="voice-hint">{t("voiceNeedVoice")}</p>}
          {engine !== "clone" && voiceChoices.length === 0 && activeEngine?.needs_voice_id && !engineVoice.trim() && (
            <p className="voice-hint">{t("voiceNeedEngineVoice")}</p>
          )}
          {engine !== "clone" && activeEngine?.note && <p className="voice-hint">{activeEngine.note}</p>}
        </div>

        <div className="voice-list-head">
          <span>{t("voiceLibrary")}</span>
          <div className="voice-head-actions">
            <Button
              size="sm"
              variant="ghost"
              onClick={() => {
                setSpeakerOpen((open) => !open);
                setUploadOpen(false);
              }}
            >
              <UsersRound size={12} /> {t("voiceFromSpeaker")}
            </Button>
            <Button
              size="sm"
              variant="outline"
              onClick={() => {
                setUploadOpen((open) => !open);
                setSpeakerOpen(false);
              }}
            >
              <Upload size={12} /> {t("voiceUpload")}
            </Button>
          </div>
        </div>

        {speakerOpen && (
          <div className="voice-upload">
            <Select
              value={spAsset}
              onValueChange={(value) => {
                setSpAsset(value);
                setSpSpeaker("");
              }}
            >
              <SelectTrigger>
                <SelectValue placeholder={t("voicePickAsset")} />
              </SelectTrigger>
              <SelectContent>
                {clipAssets.map((asset) => (
                  <SelectItem key={asset.id} value={asset.id}>
                    {asset.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            {spAsset &&
              (transcript.isError ? (
                <p className="voice-hint">{t("voiceNoTranscript")}</p>
              ) : speakers.length > 0 ? (
                <Select value={spSpeaker} onValueChange={setSpSpeaker}>
                  <SelectTrigger>
                    <SelectValue placeholder={t("voicePickSpeaker")} />
                  </SelectTrigger>
                  <SelectContent>
                    {speakers.map((speaker) => (
                      <SelectItem key={speaker} value={speaker}>
                        {speaker}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              ) : transcript.isLoading ? null : (
                <p className="voice-hint">{t("voiceNoSpeakers")}</p>
              ))}
            <Input placeholder={t("voiceName")} value={spName} onChange={(event) => setSpName(event.target.value)} />
            <div className="voice-upload-actions">
              <span className="voice-hint">{t("voiceFromSpeakerHint")}</span>
              <Button
                size="sm"
                disabled={!spAsset || !spSpeaker || fromSpeaker.isPending}
                onClick={() => fromSpeaker.mutate()}
              >
                {fromSpeaker.isPending ? <Loader2 size={12} className="spin" /> : null} {t("voiceDoClone")}
              </Button>
            </div>
          </div>
        )}

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
