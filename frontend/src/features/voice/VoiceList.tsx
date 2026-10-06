import React from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, CloudUpload, Pause, Pencil, Play, ShieldAlert, Trash2, Wand2, X } from "lucide-react";
import { toast } from "sonner";

import {
  copyVoiceToEngine,
  deleteVoice,
  listTtsEngines,
  recognizeReference,
  updateVoice,
  voiceSampleUrl,
  type RemoteCopy,
  type Voice,
  type VoiceDeleteResult,
} from "@/api/client";
import { voiceKeys } from "@/api/queryKeys";
import type { MessageKey } from "@/app/messages";
import { useI18n } from "@/app/preferences";
import { ConfirmDialog } from "@/components/app/modals";
import { Button } from "@/components/ui/button";
import { IconButton } from "@/components/ui/icon-button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Hint } from "@/components/ui/tooltip";
import { Truncate } from "@/components/ui/truncate";
import { useSamplePlayer } from "@/lib/useSamplePlayer";
import { VoiceConsentPicker, VoiceConsentStatus } from "@/features/voice/VoiceConsent";
import { isConsentDeclined, withRemoteVoiceConsent } from "@/features/voice/remoteVoiceConsent";
import { cn } from "@/lib/utils";

/**
 * 音色库的列表:试听、改名 / 补参考文本 / 补授权声明、删除。
 *
 * 剪辑页的配音面板和设置页的「声音克隆」**共用这一份**。此前两处各写一套行:剪辑页删音色不确认、
 * 删失败没提示,编辑表单里没有授权声明,没有参考音频的音色试听键照样能点 —— 同一个音色在两页上
 * 能做的事、会遇到的提醒不一样。
 *
 * 给了 `onSelect` 的是剪辑页:点一行就选中它做配音用的嗓子;设置页只管理,不选。
 */
export function VoiceList({
  workspaceId,
  voices,
  selectedId,
  onSelect,
}: {
  workspaceId: string;
  voices: Voice[];
  selectedId?: string;
  onSelect?: (voiceId: string) => void;
}) {
  const t = useI18n();
  const qc = useQueryClient();
  const invalidate = () => void qc.invalidateQueries({ queryKey: voiceKeys.all(workspaceId) });
  // 试听是开关,不是单向动作 —— 见 useSamplePlayer。
  const player = useSamplePlayer(voiceSampleUrl);
  const [editing, setEditing] = React.useState<string | null>(null);
  const [deleting, setDeleting] = React.useState<Voice | null>(null);
  //: 能把嗓子复刻上去的引擎(百炼 CosyVoice,ADR 0037),而且这个人配好了。配好了才摆「复刻到百炼」。
  const engines = useQuery({ queryKey: ["tts-engines"], queryFn: listTtsEngines, staleTime: 30_000 });
  const cloningEngine = (engines.data ?? []).find((engine) => engine.clones_voices && engine.ready)?.id ?? null;
  const remove = useMutation({
    mutationFn: (id: string) => deleteVoice(id),
    onSuccess: (result: VoiceDeleteResult | undefined) => {
      invalidate();
      setDeleting(null);
      //: 远端那份删不掉(钥匙失效、网络)也照删本机这一行 —— 但要说出来,告诉他去百炼控制台看。
      const left = result?.remote_failures ?? [];
      if (left.length === 0) {
        toast.success(t("voiceDeleted"));
        return;
      }
      toast.warning(t("voiceDeletedRemoteLeft").replace("{n}", String(left.length)), {
        description: left
          .map((one) => `${one.connection} · ${one.target_model} · ${one.remote_voice_id}:${one.reason}`)
          .join("\n"),
        duration: Infinity,
      });
    },
    onError: (error: Error) => toast.error(error.message),
  });

  return (
    <>
      {/* 分隔线,不是一行一个边框:这是一个列表,不是一叠卡片。 */}
      <div className="grid divide-y divide-border">
        {voices.map((voice) => (
          <VoiceRow
            key={voice.id}
            voice={voice}
            selected={voice.id === selectedId}
            onSelect={onSelect ? () => onSelect(voice.id) : undefined}
            playing={player.playingId === voice.id}
            onPlay={() => player.toggle(voice.id)}
            editing={editing === voice.id}
            onToggleEdit={() => setEditing(editing === voice.id ? null : voice.id)}
            onChanged={invalidate}
            onDelete={() => setDeleting(voice)}
            cloningEngine={cloningEngine}
          />
        ))}
      </div>
      <ConfirmDialog
        open={deleting !== null}
        title={t("voiceDeleteTitle")}
        // 删音色不会动已经生成的配音(那些是素材),但**这把嗓子以后配不出来了** —— 说清楚。
        // 复刻到百炼过的,百炼上的副本也一起删(当初同意上传时就是这么说的)。
        body={`${t("voiceDeleteBody").replace("{name}", deleting?.name ?? "")}${
          deleting?.remote_copies?.length ? ` ${t("voiceDeleteRemoteToo")}` : ""
        }`}
        onCancel={() => setDeleting(null)}
        pending={remove.isPending}
        onConfirm={() => {
          if (deleting) remove.mutate(deleting.id);
        }}
      />
    </>
  );
}

/**
 * **一行就是一行,不是一张表单。** 默认只显示名字、来源和参考文本首行;编辑要点一下才展开。
 * 试听走一个播放按钮(原生 audio 控件又高又占地方,而且每行一个)。
 */
function VoiceRow({
  voice,
  selected,
  onSelect,
  playing,
  onPlay,
  editing,
  onToggleEdit,
  onChanged,
  onDelete,
  cloningEngine,
}: {
  voice: Voice;
  selected: boolean;
  onSelect?: () => void;
  playing: boolean;
  onPlay: () => void;
  editing: boolean;
  onToggleEdit: () => void;
  onChanged: () => void;
  onDelete: () => void;
  /** 能把嗓子复刻上去、这个人也配好了的引擎;null = 不摆「复刻到百炼」。 */
  cloningEngine: string | null;
}) {
  const t = useI18n();
  const [name, setName] = React.useState(voice.name);
  const [text, setText] = React.useState(voice.reference_text);
  // 服务端的值变了(别处改过、或者刚识别完参考文本)就跟上。
  React.useEffect(() => setName(voice.name), [voice.name]);
  React.useEffect(() => setText(voice.reference_text), [voice.reference_text]);

  const save = useMutation({
    mutationFn: (body: { name?: string; reference_text?: string }) => updateVoice(voice.id, body),
    onSuccess: () => {
      onChanged();
      onToggleEdit(); // 存完收起来 —— 编辑是临时状态,不是这一行的常态
    },
    onError: (error: Error) => toast.error(error.message),
  });
  //: 授权声明单独存,点了就存 —— 它不是名字那样要「改完再存」的草稿,选的就是一次声明(谁、何时由服务端记)。
  const declare = useMutation({
    mutationFn: (consent_kind: string) => updateVoice(voice.id, { consent_kind }),
    onSuccess: () => onChanged(),
    onError: (error: Error) => toast.error(error.message),
  });
  //: 复刻到百炼(ADR 0037):这个账号没同意过就弹确认框(说清传到哪、存多久、删嗓子会一起删),同意了排一个复刻任务。
  //: 复刻好了任务中心说一声、这一行跟着刷新(任务改动的是配音库)。
  const copy = useMutation({
    mutationFn: (engine: string) => withRemoteVoiceConsent(() => copyVoiceToEngine(voice.id, { engine })),
    onSuccess: () => {
      onChanged();
      toast.message(t("voiceCopyQueued").replace("{name}", voice.name));
    },
    onError: (error: Error) => {
      if (!isConsentDeclined(error)) toast.error(error.message);
    },
  });
  // 识别完服务端已经存下了参考文本,这里只是刷新。
  const recognize = useMutation({
    mutationFn: () => recognizeReference(voice.id),
    onSuccess: () => {
      onChanged();
      toast.success(t("voiceRecognized"));
    },
    onError: (error: Error) => toast.error(error.message),
  });

  const origin =
    voice.source === "speaker" && voice.source_speaker
      ? t("voiceFromSpeakerTag").replace("{speaker}", voice.source_speaker)
      : t("voiceFromUploadTag");
  const dirty = name.trim() !== voice.name || text !== voice.reference_text;
  // 编辑中不响应「点一行选中」:在输入框里点一下不该顺手换掉配音用的嗓子。
  const selectable = Boolean(onSelect) && !editing;
  // 名字 + 说明是这一行的摘要。能选时它本身就是那颗「选中」按钮(键盘能 Tab 到、Enter / Space 能按);
  // 试听、编辑、删除和「补授权声明」是它旁边的兄弟按钮,不嵌在里面 —— 按钮里套按钮,读屏和键盘都会乱。
  const summary = (
    <>
      <Truncate className={cn("text-ui-sm text-foreground", selected && "font-medium")}>{voice.name}</Truncate>
      {/* 第二行是这条音色的"说明":来源 + 参考文本。首行只留名字,读起来才有主次。 */}
      <Truncate className="text-ui-2xs leading-[1.5] text-muted-foreground">
        <span className="text-muted-foreground/70">{origin}</span>
        {voice.reference_text ? (
          ` · ${voice.reference_text}`
        ) : (
          // 没有参考文本时**说出来**:Fish Speech 拿不到它就合成不出能听的东西,
          // 而这条音色在下拉里看起来和别的一样正常。
          <>
            {" · "}
            <span className="text-destructive">{t("voiceNoReferenceText")}</span>
          </>
        )}
      </Truncate>
    </>
  );

  return (
    // 按钮相对**整行**(名字 + 底下那句说明)居中,而不是贴着名字那一行 —— 所以文字自成一列、
    // 按钮是另一列,由 items-center 管这两列的竖向关系。
    <div
      className={cn(
        "flex min-w-0 items-center gap-2 py-2",
        onSelect ? "rounded-md px-2" : "first:pt-0 last:pb-0",
        selectable && "hover:bg-secondary",
        selected && "bg-[color-mix(in_srgb,var(--primary)_8%,transparent)] hover:bg-[color-mix(in_srgb,var(--primary)_8%,transparent)]",
      )}
      data-voice-row={voice.id}
    >
      <div className="grid min-w-0 flex-1 gap-0.5">
        {editing ? (
          <>
            <Input
              size="sm"
              className="min-w-0"
              aria-label={t("voiceName")}
              value={name}
              onChange={(event) => setName(event.target.value)}
              autoFocus
            />
            <div className="mt-1 grid gap-1.5">
              <Textarea rows={2} value={text} placeholder={t("voiceRefText")} onChange={(event) => setText(event.target.value)} />
              <small className="text-ui-xs leading-[1.4] text-muted-foreground">{t("voiceEditHint")}</small>
              <VoiceConsentPicker
                name={`voice-consent-${voice.id}`}
                value={voice.consent_kind}
                disabled={declare.isPending}
                onChange={(kind) => declare.mutate(kind)}
              />
              <VoiceConsentStatus kind={voice.consent_kind} declaredAt={voice.consent_at} />
              <div className="flex items-center justify-between gap-2">
                {/* 让本机的转写引擎听一遍参考音频把文本填上 —— 比让用户打一遍自己说过的话强。 */}
                <Button
                  size="sm"
                  variant="ghost"
                  disabled={!voice.has_reference}
                  loading={recognize.isPending}
                  onClick={() => recognize.mutate()}
                >
                  <Wand2 size={12} /> {t("voiceRecognize")}
                </Button>
                <Button
                  size="sm"
                  disabled={!dirty}
                  loading={save.isPending}
                  onClick={() => save.mutate({ name: name.trim(), reference_text: text })}
                >
                  <Check size={12} /> {t("save")}
                </Button>
              </div>
            </div>
          </>
        ) : (
          <>
            {selectable ? (
              <button
                type="button"
                aria-current={selected || undefined}
                className="grid min-w-0 cursor-pointer gap-0.5 rounded-sm border-0 bg-transparent p-0 text-left focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
                onClick={onSelect}
              >
                {summary}
              </button>
            ) : (
              <div className="grid min-w-0 gap-0.5">{summary}</div>
            )}
            <VoicePlaces copies={voice.remote_copies ?? []} />
            {/* 升级前建的音色没有声明:用于数字人之前要补上(点编辑在那里选)。已声明的不多占一行。 */}
            {voice.consent_kind === "undeclared" && (
              <button
                type="button"
                data-voice-consent-missing=""
                className="flex cursor-pointer items-center gap-1 border-0 bg-transparent p-0 text-left text-ui-2xs text-warning hover:underline"
                onClick={onToggleEdit}
              >
                <ShieldAlert size={11} /> {t("voiceConsentMissing")}
              </button>
            )}
          </>
        )}
      </div>
      {/* **常驻显示,不藏在 hover 后面。** 藏起来省的是一点视觉噪声,代价是"这一行能干什么"
          要靠试出来 —— 而这三件事(试听、改名、删)正是来这个库的理由。 */}
      <div className="flex shrink-0 items-center gap-0.5">
        <IconButton
          size="icon-xs"
          variant="ghost"
          className={cn("text-muted-foreground hover:text-foreground", playing && "text-primary")}
          // 没有参考音频(文件丢了)就没有东西可放:灰掉,而不是点了没声音。
          disabled={!voice.has_reference}
          disabledReason={t("voiceReferenceMissing")}
          label={playing ? t("voiceStopPreview") : t("voicePlay")}
          onClick={onPlay}
        >
          {playing ? <Pause size={12} /> : <Play size={12} />}
        </IconButton>
        {cloningEngine && (
          <IconButton
            size="icon-xs"
            variant="ghost"
            className="text-muted-foreground hover:text-foreground"
            //: 没声明是谁的嗓子,不往外传(和数字人同一条线)—— 灰掉并说为什么,点编辑去补。
            disabled={voice.consent_kind === "undeclared"}
            loading={copy.isPending}
            disabledReason={voice.consent_kind === "undeclared" ? t("voiceCopyNeedsConsent") : undefined}
            label={t("voiceCopyToBailian")}
            data-voice-copy=""
            onClick={() => copy.mutate(cloningEngine)}
          >
            <CloudUpload size={12} />
          </IconButton>
        )}
        <IconButton
          size="icon-xs"
          variant="ghost"
          className="text-muted-foreground hover:text-foreground"
          label={editing ? t("cancel") : t("voiceEdit")}
          onClick={onToggleEdit}
        >
          {editing ? <X size={12} /> : <Pencil size={12} />}
        </IconButton>
        <IconButton
          size="icon-xs"
          variant="ghost"
          className="text-muted-foreground hover:text-destructive"
          label={t("delete")}
          onClick={onDelete}
        >
          <Trash2 size={12} />
        </IconButton>
      </div>
    </div>
  );
}

//: 副本状态 → 跟在「百炼 · 模型」后面的那一小截;好好的(ok)不缀。
const COPY_STATUS: Record<RemoteCopy["status"], MessageKey | null> = {
  ok: null,
  deploying: "voiceCopyDeploying",
  failed: "voiceCopyFailed",
  missing: "voiceCopyMissing",
};

/**
 * 这把嗓子在哪儿能念(ADR 0037):「本机」(参考音频就是它)和我账号里的每一份远端副本 ——「百炼 · cosyvoice-v3-flash」。
 * 没有远端副本时不多占一行:只有「本机」一种念法是默认,不值得说。
 */
function VoicePlaces({ copies }: { copies: RemoteCopy[] }) {
  const t = useI18n();
  if (copies.length === 0) return null;
  return (
    <div data-voice-places="" className="flex flex-wrap items-center gap-1 pt-0.5">
      <span className="rounded-sm bg-secondary px-1.5 py-px text-ui-2xs text-muted-foreground">{t("voicePlaceLocal")}</span>
      {copies.map((one) => {
        const suffix = COPY_STATUS[one.status];
        const broken = one.status === "failed" || one.status === "missing";
        return (
          //: 失败、被删的悬停看原因(远端的原话)。
          <Hint key={one.id} label={one.error || null}>
            <span
              data-voice-copy-status={one.status}
              className={cn(
                "rounded-sm bg-secondary px-1.5 py-px text-ui-2xs",
                broken ? "text-warning" : "text-muted-foreground",
              )}
            >
              {t("voicePlaceBailian").replace("{model}", one.target_model)}
              {suffix ? ` · ${t(suffix)}` : ""}
            </span>
          </Hint>
        );
      })}
    </div>
  );
}
