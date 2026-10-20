import React from "react";
import { useQueryClient } from "@tanstack/react-query";
import { Mic, Plus } from "lucide-react";

import type { Workspace } from "@/api/client";
import { voiceKeys } from "@/api/queryKeys";
import { useI18n } from "@/app/preferences";
import { Button } from "@/components/ui/button";
import { UploadVoiceDialog } from "@/features/voice/VoiceCreationDialogs";
import { VoiceList } from "@/features/voice/VoiceList";
import { useVoiceLibrary } from "@/features/voice/useVoiceLibrary";
import { SettingsBlock, SettingsEmpty, SettingsGroup } from "@/components/settings/settings-layout";

/**
 * Settings →「我的音色」这一页:这个工作区的音色库。
 *
 * 音色此前只能在剪辑页的配音面板里管 —— 要改个名字、删掉一个建废了的音色,得先打开一个项目、
 * 进剪辑、找到那块面板。列表本身(试听、编辑、授权声明、删除)和剪辑页是同一份 `VoiceList`,
 * 两处能做的事不会再分叉。引擎装没装、怎么装是另一件事:装引擎在管理页「引擎」,「这台机器上
 * 有哪几个引擎能用」写在「能力提供方 → 配音」那张卡里。
 *
 * **这一节没有并进页头,标题留着(维护者问过要不要删)。** 页头(「我的音色」+ 那句
 * 「这个工作区有哪些音色、怎么建」)是结构声明里那个空组,回答的是「这一页是什么」;这一节回答的是
 * 「这些音色在哪、能拿它做什么」,并且**动作(「新建音色」)和说明都挂在它的标题旁边** ——
 * 标题删掉的话,按钮就没有标题可依(得去 `components/settings` 造一个无标题的组,不在这笔改动里),
 * 而那句操作说明要么丢、要么挤进页头那半句(页头只该说这一页是什么)。
 *
 * 新建走**上传或录制一段参考音频** —— 它不需要任何项目上下文,一个音频文件就够。
 * 「从转写出的说话人建」仍然只在剪辑页:那条路要求素材**已经转写过**(后端
 * `create_from_speaker` 上来就找 Transcript),而转写和素材的上下文都在那边。
 */
export function VoiceLibrarySection({ workspace }: { workspace: Workspace }) {
  const t = useI18n();
  const qc = useQueryClient();
  const voices = useVoiceLibrary(workspace.id);
  const invalidate = () => void qc.invalidateQueries({ queryKey: voiceKeys.all(workspace.id) });

  const list = voices.data ?? [];
  const [creating, setCreating] = React.useState(false);
  return (
    <SettingsGroup
      title={t("voiceLibrary")}
      description={t("voiceLibrarySettingsDesc")}
      // **动作归到这一节的标题旁**。放在列表下面时它排在最后一条音色之后,看着像"列表的最后
      // 一项",而不是这一节的入口 —— 而这一节本来就有 actions 插槽,别处的分组都这么用。
      actions={
        <Button size="sm" variant="outline" onClick={() => setCreating(true)}>
          <Plus size={13} /> {t("voiceNewTitle")}
        </Button>
      }
    >
      <SettingsBlock>
        {/* **不跟着引擎卡片缩进。** 那些卡片的 13px 在自己的边框**里面**,看着是合理的留白;
            无边框的列表照抄那个缩进,就只是左边空一条(真机上一眼就看出来了)。 */}
        <div className="grid gap-2">
        {voices.data && list.length === 0 ? (
          // 空状态要说清**去哪儿建另一种** —— 否则"这里不做说话人克隆"就成了死胡同。
          <SettingsEmpty icon={<Mic size={20} />} title={t("voiceLibraryEmpty")} body={t("voiceLibraryEmptyHint")} />
        ) : (
          <VoiceList workspaceId={workspace.id} voices={list} />
        )}
        </div>
      </SettingsBlock>
      <UploadVoiceDialog
        open={creating}
        workspace={workspace}
        title={t("voiceNewTitle")}
        submitLabel={t("voiceCreate")}
        onCreated={invalidate}
        onClose={() => setCreating(false)}
      />
    </SettingsGroup>
  );
}
