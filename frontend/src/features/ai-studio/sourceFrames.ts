/**
 * 生成面板里那些「带角色的输入素材」:首帧、尾帧、参考图。
 *
 * 此前每一种都在 AiStudio.tsx 里各占一套 —— 三个配置字段、一个 ref、一条上传变更、
 * 一个清除函数、六十行 JSX。加尾帧就是把这一整套再抄一遍,而抄漏的那一处不会报错。
 *
 * 收成按角色索引的一张表:加一种角色 = 描述符声明它 + 这里多一行文案,控件自己长出来。
 */

import type { MessageKey } from "@/app/messages";

/** 与后端 ai/providers/base.SOURCE_ROLES 同名。多一种要两边一起加(契约在描述符里)。 */
export const SOURCE_ROLES = ["first_frame", "last_frame", "reference_image"] as const;
export type SourceRole = (typeof SOURCE_ROLES)[number];

/** 一个槽位里放着什么:要么是素材库里的一份,要么是一条外链,两者互斥。 */
export interface FrameSlot {
  url: string;
  assetId: string;
  assetName: string;
}

export const EMPTY_SLOT: FrameSlot = { url: "", assetId: "", assetName: "" };

interface RoleCopy {
  label: MessageKey;
  upload: MessageKey;
  uploading: MessageKey;
  urlLabel: MessageKey;
}

/** 每种角色在界面上怎么称呼。控件本身是同一个。 */
export const ROLE_COPY: Record<SourceRole, RoleCopy> = {
  first_frame: {
    label: "genFirstFrame",
    upload: "genFirstFrameUpload",
    uploading: "genFirstFrameUploading",
    urlLabel: "genFirstFrameUrl",
  },
  last_frame: {
    label: "genLastFrame",
    upload: "genLastFrameUpload",
    uploading: "genLastFrameUploading",
    urlLabel: "genLastFrameUrl",
  },
  reference_image: {
    label: "genReferenceImage",
    upload: "genReferenceImageUpload",
    uploading: "genReferenceImageUploading",
    urlLabel: "genReferenceImageUrl",
  },
};

/** 提交时,把非空的槽位翻成接口要的 [{asset_id, role}]。外链走 parameters 的 <role>_url。 */
export function sourceAssetsFrom(
  frames: Record<SourceRole, FrameSlot>,
  supported: (role: SourceRole) => boolean,
): { asset_id: string; role: SourceRole }[] {
  return SOURCE_ROLES.filter((role) => supported(role) && frames[role].assetId).map((role) => ({
    asset_id: frames[role].assetId,
    role,
  }));
}

/** 外链那一半:填了 url 的槽位变成 `first_frame_url` 这样的参数。 */
export function frameUrlParameters(
  frames: Record<SourceRole, FrameSlot>,
  supported: (role: SourceRole) => boolean,
): Record<string, string> {
  const params: Record<string, string> = {};
  for (const role of SOURCE_ROLES) {
    const url = frames[role].url.trim();
    if (supported(role) && url) params[`${role}_url`] = url;
  }
  return params;
}

export function emptyFrames(): Record<SourceRole, FrameSlot> {
  return { first_frame: { ...EMPTY_SLOT }, last_frame: { ...EMPTY_SLOT }, reference_image: { ...EMPTY_SLOT } };
}
