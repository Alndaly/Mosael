import React from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AudioLines, Loader2, Mic, Pause, Pencil, Play, Square, Trash2, Upload, UsersRound, Wand2, X } from "lucide-react";
import { toast } from "sonner";

import {
  api,
  deleteVoice,
  listAssets,
  generatePodcast,
  getTtsConfig,
  listTtsEngines,
  listTtsModels,
  listTtsVoices,
  listVoices,
  synthesizeVoice,
  synthesizeWithEngine,
  updateVoice,
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
import { Combobox } from "@/components/app/combobox";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { useSamplePlayer } from "@/features/editor/useSamplePlayer";
import { formatBytes } from "@/lib/bytes";
import { cn } from "@/lib/utils";

/** 带小标签的紧凑表单格:配音面板的下拉全长一个样,没有标签就分不清
    「音色」「语速」「发音人 B」谁是谁 —— 标签贴在控件上方而不是靠占位符。 */
function VoiceField({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="grid min-w-0 content-start gap-1">
      <span className="text-[10.5px] font-medium leading-none text-muted-foreground">{label}</span>
      {children}
    </div>
  );
}

function VoicePicker({
  value,
  onChange,
  choices,
  ariaLabel,
}: {
  value: string;
  onChange: (value: string) => void;
  choices: { value: string; label: string }[];
  ariaLabel: string;
}) {
  return (
    <Select value={value} onValueChange={onChange}>
      <SelectTrigger className="w-full min-w-0" aria-label={ariaLabel}>
        <SelectValue />
      </SelectTrigger>
      <SelectContent>
        {choices.map((voice) => (
          <SelectItem key={voice.value} value={voice.value}>
            {voice.label}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}

function SpeedPicker({ value, onChange, ariaLabel }: { value: number; onChange: (value: number) => void; ariaLabel: string }) {
  return (
    <Select value={String(value)} onValueChange={(next) => onChange(Number(next))}>
      <SelectTrigger className="w-full min-w-0" aria-label={ariaLabel}>
        <SelectValue />
      </SelectTrigger>
      <SelectContent>
        {[0.75, 1, 1.25, 1.5, 2].map((option) => (
          <SelectItem key={option} value={String(option)}>
            {option}×
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}

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
  // Remote engines take a speed multiplier (the engine paces itself — better prosody than
  // stretching the waveform afterwards). The local clone worker has no speed input, so the
  // control only renders for remote engines and the value only rides on their requests.
  const [speed, setSpeed] = React.useState(1);
  // staleTime 不能是 Infinity:这份数据里带着"本地引擎装了没有",而用户就是会在另一个页面
  // 把它装上再回来。装完了界面还说"没装",比一开始就没说更让人不知道该干嘛。
  const engines = useQuery({ queryKey: ["tts-engines"], queryFn: listTtsEngines, staleTime: 30_000 });
  // 本地引擎的就绪情况(解释器 + 权重)。设置页那个只是**默认**,这里可以按次覆盖。
  const localEngines = useQuery({ queryKey: ["tts-models"], queryFn: listTtsModels, staleTime: 30_000 });
  const ttsConfig = useQuery({ queryKey: ["tts-config"], queryFn: getTtsConfig, staleTime: 30_000 });
  const [cloneEngineChoice, setCloneEngineChoice] = React.useState("");
  const cloneEngine = cloneEngineChoice || ttsConfig.data?.engine || "f5-tts";
  const cloneModel = (localEngines.data ?? []).find((item) => item.id === cloneEngine);
  // 能出声要两件事都成立:有解释器能 import 它(runtime_ready),权重在盘上(status=installed)。
  const cloneUsable = Boolean(cloneModel && cloneModel.status === "installed" && cloneModel.runtime_ready);
  const activeEngine = engines.data?.find((item) => item.id === engine);
  // Fetched per engine rather than bundled with the engine list: 火山's catalogue depends on
  // the account, so it is a live lookup that can change without the engine list changing.
  const engineVoices = useQuery({
    queryKey: ["tts-voices", engine],
    queryFn: () => listTtsVoices(engine),
    enabled: engine !== "clone",
  });
  const voiceChoices = engineVoices.data ?? [];
  // The podcast engine is a different shape of request, not another voice: one call produces
  // a whole dialogue, so it needs two speakers and a mode rather than one voice.
  const isPodcast = engine === "volcano-podcast";
  const [podcastMode, setPodcastMode] = React.useState<"summarize" | "read" | "research">("summarize");
  const [speakerB, setSpeakerB] = React.useState("");
  const chosenVoice = voiceChoices.find((item) => item.value === (engineVoice || voiceChoices[0]?.value));
  const [uploadOpen, setUploadOpen] = React.useState(false);
  const [name, setName] = React.useState("");
  const [refText, setRefText] = React.useState("");
  const [file, setFile] = React.useState<File | null>(null);
  const fileRef = React.useRef<HTMLInputElement>(null);

  const [dragOver, setDragOver] = React.useState(false);
  // 试听是开关,不是单向动作 —— 见 useSamplePlayer。
  const sample = useSamplePlayer(voiceSampleUrl);
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

  // 「确认」点不动时,差的是哪一样。两样都缺先说音频 —— 那是这件事的主料。
  const cloneBlocker = !file ? "voiceNeedRefAudio" : !name.trim() ? "voiceNeedName" : null;

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
  // 音色能改的只有说明性字段:换了参考音频就是另一个音色,而用它生成过的配音还在时间线上。
  const [editing, setEditing] = React.useState<string | null>(null);
  const [editName, setEditName] = React.useState("");
  const [editText, setEditText] = React.useState("");
  const saveVoice = useMutation({
    mutationFn: () => updateVoice(editing as string, { name: editName, reference_text: editText }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ["voices", workspace.id] });
      setEditing(null);
    },
    onError: (error: Error) => toast.error(error.message),
  });
  const remove = useMutation({
    mutationFn: (id: string) => deleteVoice(id),
    onSuccess: () => void qc.invalidateQueries({ queryKey: ["voices", workspace.id] }),
  });
  const synth = useMutation({
    mutationFn: () =>
      isPodcast
        ? generatePodcast({
            workspace_id: workspace.id,
            project_id: project.id,
            mode: podcastMode,
            // research discusses a topic; the other two work from the text itself.
            text: podcastMode === "research" ? "" : text,
            topic: podcastMode === "research" ? text : "",
            speakers: [engineVoice || voiceChoices[0]?.value || "", speakerB].filter(Boolean),
            speed,
          })
        : engine === "clone"
        ? synthesizeVoice(activeVoice as string, { text, project_id: project.id, clone_engine: cloneEngine })
        : synthesizeWithEngine({
            workspace_id: workspace.id,
            text,
            engine,
            // The dropdown *displays* the first voice when nothing is picked — submit the same
            // thing, or the engine silently falls back to its own default.
            engine_voice: engineVoice || voiceChoices[0]?.value || "",
            // The family only the listing knows; without it 火山 answers 55000000.
            engine_voice_resource: chosenVoice?.resource_id ?? "",
            speed,
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
  const podcastSpeakers = [engineVoice || voiceChoices[0]?.value || "", speakerB || voiceChoices[1]?.value || ""];
  const engineReady =
    engine === "clone"
      // 装没装引擎,和选没选音色,是两件都得成立的事。
      ? Boolean(activeVoice) && cloneUsable
      : isPodcast
        ? podcastMode === "read"
          ? Boolean(podcastSpeakers[0])
          : podcastSpeakers.every(Boolean) && podcastSpeakers[0] !== podcastSpeakers[1]
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
    <section className="min-h-0 overflow-hidden rounded-md border border-border bg-panel shadow-[var(--shadow-panel)] grid grid-cols-[minmax(0,1fr)] grid-rows-[auto_minmax(0,1fr)]">
      <div className="flex min-h-10 items-center justify-between border-b border-border px-3 [&_h2]:m-0 [&_h2]:text-[11px] [&_h2]:font-semibold [&_h2]:uppercase [&_h2]:tracking-[0.06em] [&_h2]:text-muted-foreground">{tabs}</div>
      <div className="grid min-h-0 flex-1 content-start gap-3 overflow-y-auto p-2.5">
        <div className="grid gap-[7px] rounded-lg border border-border bg-panel p-2.5">
          <label className="flex items-center gap-1.5 text-xs font-semibold text-foreground">
            <Wand2 size={13} /> {t("voiceSynthTitle")}
          </label>
          <div className="grid gap-1.5">
            <VoiceField label={t("voiceEngine")}>
              <Select
                value={engine}
                onValueChange={(value) => {
                  setEngine(value);
                  // Voice ids do not carry across engines — "alloy" means nothing to 火山 — and
                  // the new engine's list arrives asynchronously, so clear rather than guess.
                  setEngineVoice("");
                  setSpeakerB("");
                }}
              >
                <SelectTrigger className="w-full min-w-0" aria-label={t("voiceEngine")}>
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
            </VoiceField>
            {/* 本地克隆:**音色也在这里选**。
                此前这一格是空的 —— 唯一的选法是滚到下面的音色库点一张卡,而在没点之前
                `activeVoice` 会悄悄取列表第一个。于是"我到底在用哪个音色"这件事,界面上
                一个字都没写。远程引擎的音色就在这个位置,克隆没有理由长得不一样。 */}
            {/* 这里**没有语速** —— 本地克隆的 worker 不吃这个参数(上面 speed 那段注释说的就是
                它)。摆一个拨不动的旋钮,比不摆更糟。 */}
            {engine === "clone" && (
              <div className="grid grid-cols-2 gap-1.5">
                {/* 设置页那个是默认,这一次用哪个由这一次说了算 —— 想换引擎不必跑去改全局。
                    没装好的照样列出来但标明白,而不是藏起来让人猜为什么少了一个。 */}
                <VoiceField label={t("voicePanelCloneEngine")}>
                  <Select value={cloneEngine} onValueChange={setCloneEngineChoice}>
                    <SelectTrigger className="w-full min-w-0" aria-label={t("voicePanelCloneEngine")}>
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {(localEngines.data ?? []).map((item) => (
                        <SelectItem key={item.id} value={item.id}>
                          {item.label}
                          {item.status === "installed" && item.runtime_ready ? "" : ` · ${t("voiceCloneEngineUnready")}`}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </VoiceField>
                <VoiceField label={t("voiceLibraryPick")}>
                  {list.length > 0 ? (
                    <Select value={activeVoice ?? ""} onValueChange={setSelected}>
                      <SelectTrigger className="w-full min-w-0" aria-label={t("voiceLibraryPick")}>
                        <SelectValue placeholder={t("voiceLibraryPickPlaceholder")} />
                      </SelectTrigger>
                      <SelectContent>
                        {list.map((voice) => (
                          <SelectItem key={voice.id} value={voice.id}>
                            {voice.name}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  ) : (
                    <p className="m-0 text-[11px] leading-[26px] text-muted-foreground">{t("voiceLibraryPickEmpty")}</p>
                  )}
                </VoiceField>
              </div>
            )}
            {/* 单人远程引擎:音色 + 语速 同行,标签说明谁是谁 */}
            {engine !== "clone" && !isPodcast && voiceChoices.length > 0 && (
              <div className="grid grid-cols-[minmax(0,1fr)_88px] gap-1.5">
                <VoiceField label={t("voiceEngineVoice")}>
                  <VoicePicker value={engineVoice || voiceChoices[0].value} onChange={setEngineVoice} choices={voiceChoices} ariaLabel={t("voiceEngineVoice")} />
                </VoiceField>
                <VoiceField label={t("voiceSpeed")}>
                  <SpeedPicker value={speed} onChange={setSpeed} ariaLabel={t("voiceSpeed")} />
                </VoiceField>
              </div>
            )}
            {/* 播客:两个发音人一行(A/B 一目了然),对话方式 + 语速一行 */}
            {isPodcast && voiceChoices.length > 0 && (
              <>
                <div className="grid grid-cols-2 gap-1.5">
                  <VoiceField label={t("voicePodcastSpeakerA")}>
                    <VoicePicker value={engineVoice || voiceChoices[0]?.value || ""} onChange={setEngineVoice} choices={voiceChoices} ariaLabel={t("voicePodcastSpeakerA")} />
                  </VoiceField>
                  <VoiceField label={t("voicePodcastSpeakerB")}>
                    <VoicePicker value={speakerB || voiceChoices[1]?.value || ""} onChange={setSpeakerB} choices={voiceChoices} ariaLabel={t("voicePodcastSpeakerB")} />
                  </VoiceField>
                </div>
                <div className="grid grid-cols-[minmax(0,1fr)_88px] gap-1.5">
                  <VoiceField label={t("voicePodcastMode")}>
                    <Select value={podcastMode} onValueChange={(value) => setPodcastMode(value as typeof podcastMode)}>
                      <SelectTrigger className="w-full min-w-0" aria-label={t("voicePodcastMode")}>
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="summarize">{t("voicePodcastSummarize")}</SelectItem>
                        <SelectItem value="read">{t("voicePodcastRead")}</SelectItem>
                        <SelectItem value="research">{t("voicePodcastResearch")}</SelectItem>
                      </SelectContent>
                    </Select>
                  </VoiceField>
                  <VoiceField label={t("voiceSpeed")}>
                    <SpeedPicker value={speed} onChange={setSpeed} ariaLabel={t("voiceSpeed")} />
                  </VoiceField>
                </div>
              </>
            )}
            {/* 目录拉不到、需要手填音色 id 的引擎:输入框 + 语速 */}
            {engine !== "clone" && !isPodcast && voiceChoices.length === 0 && (
              <div className="grid grid-cols-[minmax(0,1fr)_88px] gap-1.5">
                {activeEngine?.needs_voice_id ? (
                  <VoiceField label={t("voiceEngineVoiceId")}>
                    <Input
                      className="min-w-0"
                      value={engineVoice}
                      placeholder={t("voiceEngineVoiceIdHint")}
                      aria-label={t("voiceEngineVoiceId")}
                      onChange={(event) => setEngineVoice(event.target.value)}
                    />
                  </VoiceField>
                ) : (
                  <div />
                )}
                <VoiceField label={t("voiceSpeed")}>
                  <SpeedPicker value={speed} onChange={setSpeed} ariaLabel={t("voiceSpeed")} />
                </VoiceField>
              </div>
            )}
          </div>
          <Textarea
           
            placeholder={isPodcast ? t("voicePodcastPlaceholder") : t("voiceSynthPlaceholder")}
            value={text}
            rows={3}
            onChange={(event) => setText(event.target.value)}
          />
          <Button
            className="w-full"
            disabled={!text.trim() || !engineReady} loading={synth.isPending}
            onClick={() => synth.mutate()}
          >
            <Wand2 size={13} /> {t("voiceGenerate")}
          </Button>
          {engine === "clone" && !activeVoice && <p className="m-0 text-[11px] leading-[1.45] text-muted-foreground">{t("voiceNeedVoice")}</p>}
          {engine !== "clone" && voiceChoices.length === 0 && activeEngine?.needs_voice_id && !engineVoice.trim() && (
            <p className="m-0 text-[11px] leading-[1.45] text-muted-foreground">{t("voiceNeedEngineVoice")}</p>
          )}
          {isPodcast && !engineReady && <p className="m-0 text-[11px] leading-[1.45] text-muted-foreground">{t("voicePodcastNeedTwo")}</p>}
          {/* 克隆这一条的 note 会随"装没装"变 —— 以前不显示它,于是"没装"这件事只能等到
              点了生成、收到一句拒绝才知道。 */}
          {activeEngine?.note && (
            <p className={cn("m-0 text-[11px] leading-[1.45] text-muted-foreground", activeEngine.ready === false && "text-destructive")}>
              {activeEngine.note}
            </p>
          )}
        </div>

        <div className="flex items-center justify-between gap-2 text-xs font-semibold text-muted-foreground">
          <span>{t("voiceLibrary")}</span>
          <div className="flex shrink-0 gap-1">
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
          <div className="grid gap-1.5 rounded-lg border border-dashed border-border-strong p-2.5">
            <Combobox
              value={spAsset}
              options={clipAssets.map((asset) => ({ value: asset.id, label: asset.name }))}
              placeholder={t("voicePickAsset")}
              emptyText={t("cmdkEmpty")}
              className="w-full"
              onValueChange={(value) => {
                setSpAsset(value);
                setSpSpeaker("");
              }}
            />
            {spAsset &&
              (transcript.isError ? (
                <p className="m-0 text-[11px] leading-[1.45] text-muted-foreground">{t("voiceNoTranscript")}</p>
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
                <p className="m-0 text-[11px] leading-[1.45] text-muted-foreground">{t("voiceNoSpeakers")}</p>
              ))}
            <Input placeholder={t("voiceName")} value={spName} onChange={(event) => setSpName(event.target.value)} />
            <div className="flex items-center justify-between gap-2">
              <span className="m-0 text-[11px] leading-[1.45] text-muted-foreground">{t("voiceFromSpeakerHint")}</span>
              <Button
                size="sm"
                disabled={!spAsset || !spSpeaker} loading={fromSpeaker.isPending}
                onClick={() => fromSpeaker.mutate()}
              >
                {fromSpeaker.isPending ? <Loader2 size={12} className="animate-openstudio-spin" /> : null} {t("voiceDoClone")}
              </Button>
            </div>
          </div>
        )}

        {uploadOpen && (
          // 这个框一直长着虚线边 —— 那是"往这儿拖"的样子。以前它只是长得像,拖上去什么都不会
          // 发生;既然长成这样,就让它真的收。
          <div
            className={cn(
              "grid gap-1.5 rounded-lg border border-dashed border-border-strong p-2.5 transition-colors duration-100",
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
              if (dropped) setFile(dropped);
            }}
          >
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
              className="hidden"
              onChange={(event) => setFile(event.target.files?.[0] ?? null)}
            />
            {/* 选好的音频要**看得见、去得掉**。以前它只是把按钮文字换成截断的文件名 ——
                既看不出到底选没选,也没有反悔的路。 */}
            {file && !recording && (
              <div className="flex items-center gap-1.5 rounded-md border border-border bg-secondary px-2 py-1">
                <AudioLines size={12} className="shrink-0 text-muted-foreground" />
                <span className="min-w-0 flex-1 truncate text-[11.5px]" title={file.name}>{file.name}</span>
                <span className="shrink-0 text-[10.5px] tabular-nums text-muted-foreground">{formatBytes(file.size)}</span>
                <button
                  type="button"
                  className="shrink-0 cursor-pointer rounded-sm border-0 bg-transparent p-0.5 leading-none text-muted-foreground hover:text-destructive"
                  aria-label={t("voiceClearFile")}
                  title={t("voiceClearFile")}
                  onClick={() => setFile(null)}
                >
                  <X size={12} />
                </button>
              </div>
            )}
            <div className="flex items-center justify-between gap-2">
              <div className="flex min-w-0 items-center gap-1">
                <Button size="sm" variant="outline" disabled={recording} onClick={() => fileRef.current?.click()}>
                  <Upload size={12} /> {file && !recording ? t("voiceReplaceFile") : t("voicePickFile")}
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
                disabled={!name.trim() || !file || recording} loading={upload.isPending}
                onClick={() => upload.mutate()}
              >
                {upload.isPending ? <Loader2 size={12} className="animate-openstudio-spin" /> : null} {t("confirm")}
              </Button>
            </div>
            {/* 「确认」灰着的时候要说**还差什么**。以前这里永远是同一句通用说明,
                于是按钮为什么点不动只能靠猜。 */}
            <p className={cn("m-0 text-[11px] leading-[1.45] text-muted-foreground", cloneBlocker && "text-destructive")}>
              {recording ? t("voiceRecording") : cloneBlocker ? t(cloneBlocker) : t("voiceUploadHint")}
            </p>
          </div>
        )}

        <div className="grid gap-1.5">
          {list.map((voice) => (
            <div
              key={voice.id}
              className={cn("flex cursor-pointer items-center justify-between gap-2 rounded-md border border-border bg-background px-2.5 py-2 transition-[border-color,background] duration-100 hover:bg-secondary", voice.id === activeVoice && "border-primary bg-[color-mix(in_srgb,var(--primary)_8%,transparent)] hover:bg-[color-mix(in_srgb,var(--primary)_8%,transparent)]")}
              role="button"
              tabIndex={0}
              onClick={() => setSelected(voice.id)}
            >
              <div className="flex min-w-0 items-center gap-2 [&>svg]:shrink-0 [&>svg]:text-primary">
                <Mic size={13} />
                <div className="grid min-w-0 [&_small]:truncate [&_small]:text-[11px] [&_small]:text-muted-foreground [&_strong]:text-[12.5px]">
                  <strong>{voice.name}</strong>
                  {/* 没有参考文本时**说出来**,而不是留一片空白:Fish Speech 拿不到它就合成不出
                      能听的东西,而这条音色在下拉里看起来和别的一样正常。 */}
                  {voice.reference_text ? (
                    <small>{voice.reference_text}</small>
                  ) : (
                    <small className="text-destructive!">{t("voiceNoReferenceText")}</small>
                  )}
                </div>
              </div>
              <div className="flex shrink-0 gap-0.5 [&_button]:grid [&_button]:h-6 [&_button]:w-6 [&_button]:cursor-pointer [&_button]:place-items-center [&_button]:rounded [&_button]:border-0 [&_button]:bg-transparent [&_button]:text-muted-foreground [&_button:hover]:bg-secondary [&_button:hover]:text-foreground">
                <button
                  type="button"
                  title={t("voiceEdit")}
                  aria-label={t("voiceEdit")}
                  onClick={(event) => {
                    event.stopPropagation();
                    setEditing(voice.id);
                    setEditName(voice.name);
                    setEditText(voice.reference_text ?? "");
                  }}
                >
                  <Pencil size={12} />
                </button>
                <button
                  type="button"
                  title={sample.playingId === voice.id ? t("voiceStopPreview") : t("voicePlay")}
                  aria-label={sample.playingId === voice.id ? t("voiceStopPreview") : t("voicePlay")}
                  className={cn(sample.playingId === voice.id && "text-primary!")}
                  onClick={(event) => {
                    event.stopPropagation();
                    sample.toggle(voice.id);
                  }}
                >
                  {sample.playingId === voice.id ? <Pause size={12} /> : <Play size={12} />}
                </button>
                <button
                  type="button"
                  title={t("delete")}
                  disabled={remove.isPending && remove.variables === voice.id}
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
          {list.length === 0 && !voices.isLoading && <p className="m-0 px-2 py-4 text-center text-xs text-muted-foreground">{t("voiceEmpty")}</p>}
        </div>
      </div>
    </section>
  );
}
