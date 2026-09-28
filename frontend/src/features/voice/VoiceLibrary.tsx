import React from "react";
import { useQueryClient } from "@tanstack/react-query";
import { Mic, Upload, UsersRound } from "lucide-react";

import type { Project, Voice, Workspace } from "@/api/client";
import { useI18n } from "@/app/preferences";
import { EmptyState } from "@/components/layout/EmptyState";
import { Button } from "@/components/ui/button";
import { UploadVoiceDialog, VoiceFromSpeakerDialog } from "@/features/voice/VoiceCreationDialogs";
import { VoiceList } from "@/features/voice/VoiceList";

/**
 * 剪辑页配音面板里的音色库:列表(和设置页共用 VoiceList)、新建、选中一条做配音。
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
  // 新建表单放在弹窗里:放进这一列的话,表单一展开整个音色库就跟着跳。
  const [uploadOpen, setUploadOpen] = React.useState(false);
  const [speakerOpen, setSpeakerOpen] = React.useState(false);

  const created = (voice: Voice) => {
    void qc.invalidateQueries({ queryKey: ["voices", workspace.id] });
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

      {voices.length > 0 && <VoiceList workspaceId={workspace.id} voices={voices} selectedId={selectedId} onSelect={onSelect} />}
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
