import React from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AudioLines, Check, Mic, Pause, Pencil, Play, Plus, Trash2, Upload, Wand2, X } from "lucide-react";
import { toast } from "sonner";

import {
  deleteVoice,
  listVoices,
  recognizeReference,
  updateVoice,
  uploadVoice,
  voiceSampleUrl,
  type Voice,
  type Workspace,
} from "@/api/client";
import { useI18n } from "@/app/preferences";
import { ConfirmDialog } from "@/components/app/modals";
import { Button } from "@/components/ui/button";
import { EmptyState } from "@/components/layout/EmptyState";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { useSamplePlayer } from "@/features/editor/useSamplePlayer";
import { formatBytes } from "@/lib/bytes";
import { SettingsBlock, SettingsGroup } from "@/features/settings/ui";

/**
 * Settings →「声音克隆」里的音色库。
 *
 * 音色此前只能在剪辑页的配音面板里管 —— 要改个名字、删掉一个建废了的音色,得先打开一个项目、
 * 进剪辑、找到那块面板。而这一页管的正是克隆这件事的其余部分(引擎、权重、解释器)。
 *
 * **一行就是一行,不是一张表单。** 第一版给每条音色套了卡片边框,里面塞两个输入框、一个原生
 * `<audio>` 控件和两个按钮 —— 三条音色就是三层嵌套的框,而绝大多数时候用户只是想看一眼有哪些。
 * 现在默认只显示名字、来源和参考文本首行;编辑要点一下才展开,操作按钮 hover 才亮;
 * 试听走一个播放按钮(原生 audio 控件又高又占地方,而且每行一个)。
 *
 * 新建走**上传一段参考音频** —— 它不需要任何项目上下文,一个音频文件就够。
 * 「从转写出的说话人建」仍然只在剪辑页:那条路要求素材**已经转写过**(后端
 * `create_from_speaker` 上来就找 Transcript),而转写和素材的上下文都在那边。
 */
export function VoiceLibrarySection({ workspace }: { workspace: Workspace }) {
  const t = useI18n();
  const qc = useQueryClient();
  const voices = useQuery({
    queryKey: ["voices", workspace.id],
    queryFn: () => listVoices(workspace.id),
  });
  const invalidate = () => void qc.invalidateQueries({ queryKey: ["voices", workspace.id] });
  const player = useSamplePlayer(voiceSampleUrl);

  const remove = useMutation({
    mutationFn: (id: string) => deleteVoice(id),
    onSuccess: () => {
      invalidate();
      toast.success(t("voiceDeleted"));
    },
    onError: (error: Error) => toast.error(error.message),
  });
  const [deleting, setDeleting] = React.useState<Voice | null>(null);
  const [editing, setEditing] = React.useState<string | null>(null);

  const list = voices.data ?? [];
  return (
    <SettingsGroup title={t("voiceLibrary")} description={t("voiceLibrarySettingsDesc")}>
      <SettingsBlock>
        {/* **不跟着引擎卡片缩进。** 那些卡片的 13px 在自己的边框**里面**,看着是合理的留白;
            无边框的列表照抄那个缩进,就只是左边空一条(真机上一眼就看出来了)。 */}
        <div className="grid gap-2">
        {voices.data && list.length === 0 ? (
          // 空状态要说清**去哪儿建另一种** —— 否则"这里不做说话人克隆"就成了死胡同。
          <EmptyState icon={<Mic size={20} />} title={t("voiceLibraryEmpty")} body={t("voiceLibraryEmptyHint")} />
        ) : (
          // 分隔线,不是一行一个边框:这是一个列表,不是一叠卡片。
          <div className="grid divide-y divide-border">
            {list.map((voice) => (
              <VoiceRow
                key={voice.id}
                voice={voice}
                playing={player.playingId === voice.id}
                onPlay={() => player.toggle(voice.id)}
                editing={editing === voice.id}
                onToggleEdit={() => setEditing(editing === voice.id ? null : voice.id)}
                onChanged={invalidate}
                onDelete={() => setDeleting(voice)}
              />
            ))}
          </div>
        )}
        <NewVoiceForm workspace={workspace} onCreated={invalidate} />
        </div>
      </SettingsBlock>
      <ConfirmDialog
        open={deleting !== null}
        title={t("voiceDeleteTitle")}
        // 删音色不会动已经生成的配音(那些是素材),但**这把嗓子以后配不出来了** —— 说清楚。
        body={t("voiceDeleteBody").replace("{name}", deleting?.name ?? "")}
        onCancel={() => setDeleting(null)}
        onConfirm={() => {
          if (deleting) remove.mutate(deleting.id);
          setDeleting(null);
        }}
      />
    </SettingsGroup>
  );
}

function VoiceRow({
  voice,
  playing,
  onPlay,
  editing,
  onToggleEdit,
  onChanged,
  onDelete,
}: {
  voice: Voice;
  playing: boolean;
  onPlay: () => void;
  editing: boolean;
  onToggleEdit: () => void;
  onChanged: () => void;
  onDelete: () => void;
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

  return (
    <div className="grid min-w-0 gap-0.5 py-2 first:pt-0 last:pb-0">
      <div className="flex min-w-0 items-center gap-2">
        {editing ? (
          <Input
            className="h-7 min-w-0 flex-1"
            value={name}
            onChange={(event) => setName(event.target.value)}
            autoFocus
          />
        ) : (
          <span className="min-w-0 flex-1 truncate text-ui-sm text-foreground">{voice.name}</span>
        )}
        {/* **常驻显示,不藏在 hover 后面。** 藏起来省的是一点视觉噪声,代价是"这一行能干什么"
            要靠试出来 —— 而这三件事(试听、改名、删)正是来这一页的理由。ghost + 小尺寸
            已经够轻,不至于抢掉名字的视线。 */}
        <div className="flex shrink-0 items-center gap-0.5">
          <Button
            size="icon"
            variant="ghost"
            className="h-7 w-7"
            disabled={!voice.has_reference}
            aria-label={playing ? t("voiceStopPreview") : t("voicePlay")}
            onClick={onPlay}
          >
            {playing ? <Pause size={13} /> : <Play size={13} />}
          </Button>
          <Button
            size="icon"
            variant="ghost"
            className="h-7 w-7"
            aria-label={editing ? t("cancel") : t("rename")}
            onClick={onToggleEdit}
          >
            {editing ? <X size={13} /> : <Pencil size={13} />}
          </Button>
          <Button size="icon" variant="ghost" className="h-7 w-7" aria-label={t("delete")} onClick={onDelete}>
            <Trash2 size={13} />
          </Button>
        </div>
      </div>

      {editing ? (
        <div className="mt-1 grid gap-1.5">
          <Textarea
            rows={2}
            value={text}
            placeholder={t("voiceReferenceTextOptional")}
            onChange={(event) => setText(event.target.value)}
          />
          <div className="flex items-center justify-between gap-2">
            {/* 让本机的转写引擎听一遍参考音频把文本填上 —— 比让用户打一遍自己说过的话强。 */}
            <Button size="sm" variant="ghost" loading={recognize.isPending} onClick={() => recognize.mutate()}>
              <Wand2 size={12} /> {t("voiceRecognize")}
            </Button>
            <Button size="sm" disabled={!dirty} loading={save.isPending}
              onClick={() => save.mutate({ name: name.trim(), reference_text: text })}>
              <Check size={12} /> {t("save")}
            </Button>
          </div>
        </div>
      ) : (
        // 第二行是这条音色的"说明":来源 + 参考文本。首行只留名字和操作,读起来才有主次。
        <p className="m-0 truncate text-ui-2xs leading-[1.5] text-muted-foreground" title={voice.reference_text}>
          <span className="text-muted-foreground/70">{origin}</span>
          {voice.reference_text ? ` · ${voice.reference_text}` : ""}
        </p>
      )}
    </div>
  );
}

/** 新建音色:传一段参考音频。**参考文本可以留空** —— 建完点那一行的编辑、再点「识别」,
    让本机转写引擎听一遍填上,比让用户当场打一遍自己说过的话强。 */
function NewVoiceForm({ workspace, onCreated }: { workspace: Workspace; onCreated: () => void }) {
  const t = useI18n();
  const [open, setOpen] = React.useState(false);
  const [name, setName] = React.useState("");
  const [refText, setRefText] = React.useState("");
  const [file, setFile] = React.useState<File | null>(null);
  const fileRef = React.useRef<HTMLInputElement | null>(null);

  const upload = useMutation({
    mutationFn: () => uploadVoice({ workspaceId: workspace.id, name, referenceText: refText, file: file as File }),
    onSuccess: () => {
      onCreated();
      setOpen(false);
      setName("");
      setRefText("");
      setFile(null);
      toast.success(t("voiceCreated"));
    },
    onError: (error: Error) => toast.error(error.message),
  });

  if (!open) {
    return (
      <Button size="sm" variant="outline" className="mt-1.5 justify-self-start" onClick={() => setOpen(true)}>
        <Plus size={13} /> {t("voiceNewTitle")}
      </Button>
    );
  }
  return (
    <div className="mt-1.5 grid gap-1.5 rounded-lg border border-dashed border-border-strong p-2.5">
      <Input placeholder={t("voiceName")} value={name} onChange={(event) => setName(event.target.value)} autoFocus />
      <Textarea
        rows={2}
        placeholder={t("voiceReferenceTextOptional")}
        value={refText}
        onChange={(event) => setRefText(event.target.value)}
      />
      <input
        ref={fileRef}
        type="file"
        accept="audio/*,video/*"
        className="hidden"
        onChange={(event) => setFile(event.target.files?.[0] ?? null)}
      />
      {/* 选好的音频要**看得见、去得掉** —— 只把按钮文字换成文件名的话,既看不出选没选,
          也没有反悔的路(剪辑页那处踩过这个)。 */}
      {file && (
        <div className="flex min-w-0 items-center gap-1.5 rounded-md border border-border bg-secondary px-2 py-1">
          <AudioLines size={12} className="shrink-0 text-muted-foreground" />
          <span className="min-w-0 flex-1 truncate text-ui-xs" title={file.name}>{file.name}</span>
          <span className="shrink-0 text-ui-2xs tabular-nums text-muted-foreground">{formatBytes(file.size)}</span>
          <button
            type="button"
            className="shrink-0 cursor-pointer rounded-sm border-0 bg-transparent p-0.5 leading-none text-muted-foreground hover:text-destructive"
            aria-label={t("voiceClearFile")}
            onClick={() => setFile(null)}
          >
            <X size={12} />
          </button>
        </div>
      )}
      <div className="flex items-center justify-between gap-2">
        <Button size="sm" variant="outline" onClick={() => fileRef.current?.click()}>
          <Upload size={12} /> {file ? t("voiceReplaceFile") : t("voicePickFile")}
        </Button>
        <div className="flex items-center gap-1.5">
          <Button size="sm" variant="ghost" onClick={() => setOpen(false)}>
            {t("cancel")}
          </Button>
          <Button
            size="sm"
            // 缺什么就说缺什么 —— 一个点不动而不给理由的按钮,和坏了没区别。
            title={!file ? t("voiceNeedRefAudioHere") : !name.trim() ? t("voiceNeedName") : undefined}
            disabled={!name.trim() || !file}
            loading={upload.isPending}
            onClick={() => upload.mutate()}
          >
            {t("voiceCreate")}
          </Button>
        </div>
      </div>
    </div>
  );
}
