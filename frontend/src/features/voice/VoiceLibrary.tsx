import React from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Mic, Pause, Pencil, Play, Sparkles, Trash2, Upload, UsersRound } from "lucide-react";
import { toast } from "sonner";

import { deleteVoice, recognizeReference, updateVoice, voiceSampleUrl, type Project, type Voice, type Workspace } from "@/api/client";
import { useI18n } from "@/app/preferences";
import { EmptyState } from "@/components/layout/EmptyState";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { useSamplePlayer } from "@/features/editor/useSamplePlayer";
import { UploadVoiceDialog, VoiceFromSpeakerDialog } from "@/features/voice/VoiceCreationDialogs";
import { cn } from "@/lib/utils";

/**
 * 本地克隆用的音色库:列表、试听、改说明、删除、新建。
 *
 * 只在选了「本地克隆」时出现 —— 远端引擎有自己的目录,在它们下面摆这个库暗示了一层并不存在的关系。
 * 「从说话人提取」要一个项目(从这个项目的素材里挑一段),没有项目的地方就不给这个入口。
 */
export function VoiceLibrary({
  workspace,
  project,
  voices,
  loading,
  selectedId,
  onSelect,
}: {
  workspace: Workspace;
  project?: Project;
  voices: Voice[];
  loading: boolean;
  selectedId: string;
  onSelect: (voiceId: string) => void;
}) {
  const t = useI18n();
  const qc = useQueryClient();
  const refresh = () => void qc.invalidateQueries({ queryKey: ["voices", workspace.id] });
  // 试听是开关,不是单向动作 —— 见 useSamplePlayer。
  const sample = useSamplePlayer(voiceSampleUrl);
  // 新建表单放在弹窗里:放进这一列的话,表单一展开整个音色库就跟着跳。
  const [uploadOpen, setUploadOpen] = React.useState(false);
  const [speakerOpen, setSpeakerOpen] = React.useState(false);

  // 音色能改的只有说明性字段:换了参考音频就是另一个音色,而用它生成过的配音还在时间线上。
  const [editing, setEditing] = React.useState<string | null>(null);
  const [editName, setEditName] = React.useState("");
  const [editText, setEditText] = React.useState("");
  const saveVoice = useMutation({
    mutationFn: () => updateVoice(editing as string, { name: editName, reference_text: editText }),
    onSuccess: () => {
      refresh();
      setEditing(null);
    },
    onError: (error: Error) => toast.error(error.message),
  });
  const recognize = useMutation({
    mutationFn: () => recognizeReference(editing as string),
    onSuccess: (voice) => {
      setEditText(voice.reference_text ?? "");
      refresh();
      toast.success(t("voiceRecognizeDone"));
    },
    onError: (error: Error) => toast.error(error.message),
  });
  const remove = useMutation({ mutationFn: (id: string) => deleteVoice(id), onSuccess: refresh });

  const created = (voice: Voice) => {
    refresh();
    onSelect(voice.id);
  };
  const createButtons = (
    <>
      {project && (
        <Button size="sm" variant="ghost" onClick={() => setSpeakerOpen(true)}>
          <UsersRound size={12} /> {t("voiceFromSpeaker")}
        </Button>
      )}
      <Button size="sm" variant={voices.length > 0 ? "outline" : "default"} onClick={() => setUploadOpen(true)}>
        <Upload size={12} /> {t("voiceUpload")}
      </Button>
    </>
  );

  return (
    <>
      <div className="flex items-center justify-between gap-2 text-xs font-semibold text-muted-foreground">
        <span>{t("voiceLibrary")}</span>
        {voices.length > 0 && <div className="flex shrink-0 gap-1">{createButtons}</div>}
      </div>

      <div className="grid gap-3">
        {voices.map((voice) => (
          <div
            key={voice.id}
            className={cn(
              "flex cursor-pointer items-center justify-between gap-2 rounded-md border border-border bg-background px-2.5 py-2 transition-[border-color,background] duration-100 hover:bg-secondary",
              voice.id === selectedId && "border-primary bg-[color-mix(in_srgb,var(--primary)_8%,transparent)] hover:bg-[color-mix(in_srgb,var(--primary)_8%,transparent)]",
            )}
            role="button"
            tabIndex={0}
            onClick={() => onSelect(voice.id)}
          >
            <div className="flex min-w-0 items-center gap-2 [&>svg]:shrink-0 [&>svg]:text-primary">
              <Mic size={13} />
              <div className="grid min-w-0 [&_small]:truncate [&_small]:text-ui-xs [&_small]:text-muted-foreground [&_strong]:text-ui-sm">
                <strong>{voice.name}</strong>
                {/* 没有参考文本时**说出来**:Fish Speech 拿不到它就合成不出能听的东西,
                    而这条音色在下拉里看起来和别的一样正常。 */}
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
                aria-label={t("delete")}
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
        {editing && (
          <div className="grid gap-1.5 rounded-md border border-dashed border-border-strong p-2.5">
            <Input value={editName} placeholder={t("voiceName")} onChange={(event) => setEditName(event.target.value)} />
            <Textarea value={editText} rows={2} placeholder={t("voiceRefText")} onChange={(event) => setEditText(event.target.value)} />
            <small className="text-ui-xs leading-[1.4] text-muted-foreground">{t("voiceEditHint")}</small>
            <div className="flex items-center justify-end gap-1.5">
              {/* 应用自己就有转写引擎 —— 让用户打一遍自己说过的话没道理。 */}
              <Button size="sm" variant="outline" loading={recognize.isPending} onClick={() => recognize.mutate()}>
                <Sparkles size={12} /> {t("voiceRecognizeReference")}
              </Button>
              <Button size="sm" variant="ghost" onClick={() => setEditing(null)}>
                {t("cancel")}
              </Button>
              <Button size="sm" loading={saveVoice.isPending} onClick={() => saveVoice.mutate()}>
                {t("save")}
              </Button>
            </div>
          </div>
        )}
        {voices.length === 0 && !loading && (
          <EmptyState
            size="compact"
            icon={<Mic size={16} />}
            title={t("voiceLibraryEmpty")}
            body={t("voiceEmpty")}
            className="my-1 max-w-none! py-5 [&>div:first-child]:border-0 [&>div:first-child]:bg-transparent"
            action={<div className="mt-1 flex flex-wrap items-center justify-center gap-1.5">{createButtons}</div>}
          />
        )}
      </div>

      {project && (
        <VoiceFromSpeakerDialog
          open={speakerOpen}
          workspace={workspace}
          project={project}
          onCreated={created}
          onClose={() => setSpeakerOpen(false)}
        />
      )}
      <UploadVoiceDialog open={uploadOpen} workspace={workspace} onCreated={created} onClose={() => setUploadOpen(false)} />
    </>
  );
}
