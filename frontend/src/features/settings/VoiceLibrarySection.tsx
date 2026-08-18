import React from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { AudioLines, Mic, Plus, Trash2, Upload, Wand2, X } from "lucide-react";
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
import { formatBytes } from "@/lib/bytes";
import { SettingsBlock, SettingsGroup } from "@/features/settings/ui";

/**
 * Settings →「声音克隆」里的音色库。
 *
 * 音色此前**只能在剪辑页的配音面板里管** —— 要改个名字、删掉一个建废了的音色,得先打开一个
 * 项目、进剪辑、找到那块面板。而这一页管的正是克隆这件事的其余部分(引擎、权重、解释器),
 * 唯独"用哪把嗓子"不在这儿。
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

  const remove = useMutation({
    mutationFn: (id: string) => deleteVoice(id),
    onSuccess: () => {
      invalidate();
      toast.success(t("voiceDeleted"));
    },
    onError: (error: Error) => toast.error(error.message),
  });
  const [deleting, setDeleting] = React.useState<Voice | null>(null);

  return (
    <SettingsGroup title={t("voiceLibrary")} description={t("voiceLibrarySettingsDesc")}>
      <SettingsBlock>
        <NewVoiceForm workspace={workspace} onCreated={invalidate} />
        {voices.data && voices.data.length === 0 ? (
          // 空状态要说清**去哪儿建**:这一页故意不做创建(见文件头),不指路就成了死胡同。
          <EmptyState icon={<Mic size={20} />} title={t("voiceLibraryEmpty")} body={t("voiceLibraryEmptyHint")} />
        ) : (
          <div className="grid gap-2">
            {(voices.data ?? []).map((voice) => (
              <VoiceRow key={voice.id} voice={voice} onChanged={invalidate} onDelete={() => setDeleting(voice)} />
            ))}
          </div>
        )}
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

function VoiceRow({ voice, onChanged, onDelete }: { voice: Voice; onChanged: () => void; onDelete: () => void }) {
  const t = useI18n();
  const [name, setName] = React.useState(voice.name);
  const [text, setText] = React.useState(voice.reference_text);
  // 服务端的值变了(别处改过、或者刚识别完参考文本)就跟上,而**正在输入时不覆盖** ——
  // 打一半被刷掉是最气人的那种 bug。
  React.useEffect(() => setName(voice.name), [voice.name]);
  React.useEffect(() => setText(voice.reference_text), [voice.reference_text]);

  const save = useMutation({
    mutationFn: (body: { name?: string; reference_text?: string }) => updateVoice(voice.id, body),
    onSuccess: () => onChanged(),
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

  const dirty = name !== voice.name || text !== voice.reference_text;

  return (
    <div className="grid min-w-0 gap-1.5 rounded-lg border border-border bg-panel p-2.5">
      <div className="flex min-w-0 items-center gap-2">
        <Input
          className="h-7 min-w-0 flex-1"
          value={name}
          onChange={(event) => setName(event.target.value)}
          placeholder={t("voiceName")}
        />
        <Button size="sm" variant="ghost" className="shrink-0" aria-label={t("delete")} onClick={onDelete}>
          <Trash2 size={13} />
        </Button>
      </div>
      {/* 参考音频不能换 —— 换了就是另一个音色,而用它配过的音还在时间线上(见 VoiceUpdate)。
          所以这里只给试听,不给替换。 */}
      {voice.has_reference && (
        <audio className="h-8 w-full" controls preload="none" src={voiceSampleUrl(voice.id)} />
      )}
      <div className="flex min-w-0 items-start gap-1.5">
        <Input
          className="h-7 min-w-0 flex-1"
          value={text}
          onChange={(event) => setText(event.target.value)}
          placeholder={t("voiceReferenceText")}
        />
        {/* 让本机的转写引擎听一遍参考音频把文本填上 —— 比让用户打一遍自己说过的话强。 */}
        <Button
          size="sm"
          variant="outline"
          className="h-7 shrink-0"
          loading={recognize.isPending}
          onClick={() => recognize.mutate()}
        >
          <Wand2 size={12} /> {t("voiceRecognize")}
        </Button>
      </div>
      <div className="flex items-center justify-between gap-2">
        <span className="text-ui-2xs text-muted-foreground">
          {voice.source === "speaker" && voice.source_speaker
            ? t("voiceFromSpeakerTag").replace("{speaker}", voice.source_speaker)
            : t("voiceFromUploadTag")}
        </span>
        <Button
          size="sm"
          variant="outline"
          className="h-7"
          disabled={!dirty}
          loading={save.isPending}
          onClick={() => save.mutate({ name: name.trim(), reference_text: text })}
        >
          {t("save")}
        </Button>
      </div>
    </div>
  );
}


/** 新建音色:传一段参考音频。**参考文本可以留空** —— 建完用行里那个「识别」让本机转写引擎
    听一遍填上,比让用户当场打一遍自己说过的话强。 */
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
      <Button size="sm" variant="outline" className="justify-self-start" onClick={() => setOpen(true)}>
        <Plus size={13} /> {t("voiceNewTitle")}
      </Button>
    );
  }
  return (
    <div className="grid gap-1.5 rounded-lg border border-dashed border-border-strong p-2.5">
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
