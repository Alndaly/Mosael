import React from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Mic, Trash2, Wand2 } from "lucide-react";
import { toast } from "sonner";

import {
  deleteVoice,
  listVoices,
  recognizeReference,
  updateVoice,
  voiceSampleUrl,
  type Voice,
  type Workspace,
} from "@/api/client";
import { useI18n } from "@/app/preferences";
import { ConfirmDialog } from "@/components/app/modals";
import { Button } from "@/components/ui/button";
import { EmptyState } from "@/components/layout/EmptyState";
import { Input } from "@/components/ui/input";
import { SettingsBlock, SettingsGroup } from "@/features/settings/ui";

/**
 * Settings →「声音克隆」里的音色库。
 *
 * 音色此前**只能在剪辑页的配音面板里管** —— 要改个名字、删掉一个建废了的音色,得先打开一个
 * 项目、进剪辑、找到那块面板。而这一页管的正是克隆这件事的其余部分(引擎、权重、解释器),
 * 唯独"用哪把嗓子"不在这儿。
 *
 * **不做创建。** 建音色要一段参考音频,而挑音频的上下文在剪辑页(时间线上的片段、转写出来的
 * 说话人)。把它搬过来就得把素材选择器一起搬,那是另一个页面的活。这里管的是**已有的那些**:
 * 改名、补参考文本、试听、删掉。
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
