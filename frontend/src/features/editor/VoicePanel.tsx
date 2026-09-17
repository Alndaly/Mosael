import React from "react";

import type { Project, Sequence, Workspace } from "@/api/client";
import { useI18n } from "@/app/preferences";
import { SubtitleDub } from "@/features/editor/SubtitleDub";
import { SpeechVoiceFields } from "@/features/voice/SpeechVoiceFields";
import { useSpeechVoice } from "@/features/voice/useSpeechVoice";
import { VoiceLibrary } from "@/features/voice/VoiceLibrary";

/**
 * 剪辑台的「配音」页:**只管和这条时间线有关的声音** —— 给字幕配音,以及它要用的音色库。
 *
 * 念一段任意文字、做一期播客产出的是独立的音频素材,和哪条时间线无关,在「AI 生成 → 音频」。
 * 此前它们都挤在这一栏里,而字幕配音反倒藏在「字幕」页的一个弹层里:同一个"选引擎、选声音"
 * 在两处各写一份,能调的东西还不一样。
 */
export function VoicePanel({
  workspace,
  project,
  sequence,
  onOpenSubtitles,
}: {
  workspace: Workspace;
  project: Project;
  sequence: Sequence;
  onOpenSubtitles?: () => void;
}) {
  const t = useI18n();
  const voice = useSpeechVoice(workspace.id);
  return (
    <section
      aria-label={t("voiceTab")}
      className="min-h-0 editor-pane overflow-hidden bg-workspace-panel grid grid-cols-[minmax(0,1fr)] grid-rows-[minmax(0,1fr)]"
    >
      <div className="grid min-h-0 flex-1 content-start gap-5 overflow-y-auto overflow-x-hidden p-4">
        <div className="grid gap-3">
          <SpeechVoiceFields voice={voice} />
          <SubtitleDub sequence={sequence} voice={voice} onOpenSubtitles={onOpenSubtitles} />
        </div>
        {/* 音色库只服务本地克隆;远端引擎有自己的目录,在它们下面摆这个库暗示了一层不存在的关系。 */}
        {voice.engine === "clone" && (
          <VoiceLibrary
            workspace={workspace}
            project={project}
            voices={voice.library}
            loading={voice.libraryLoading}
            selectedId={voice.voiceId}
            onSelect={voice.setVoiceId}
          />
        )}
      </div>
    </section>
  );
}
