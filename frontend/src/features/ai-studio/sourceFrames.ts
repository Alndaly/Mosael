/**
 * 生成面板里那些「带角色的输入素材」:首帧、尾帧、参考图、参考视频、参考音频。
 *
 * 此前每一种都在 AiStudio.tsx 里各占一套 —— 三个配置字段、一个 ref、一条上传变更、
 * 一个清除函数、六十行 JSX。加尾帧就是把这一整套再抄一遍,而抄漏的那一处不会报错。
 *
 * 收成按角色索引的一张表:加一种角色 = 描述符声明它 + 这里多一行文案,控件自己长出来。
 *
 * ## 首尾帧和参考素材是两条路,不是一个东西的两种叫法
 *
 * 首帧尾帧决定的是**成片的第一格和最后一格**;参考素材一帧都不出现在成片里,它只影响
 * 风格与主体。各家接口都把这条界线画成硬约束(火山原话:`first/last frame content
 * cannot be mixed with reference media content`),所以描述符里它们分属两个互斥组,
 * 界面照着 exclusiveSourceGroups 把另一组灰掉。
 *
 * ## 参考类角色可以挂多份
 *
 * 参考图九张、参考视频三段 —— 上限由描述符的 source_limits 给,读法见
 * lib/generationCapabilities.sourceLimit。所以每个角色存的是**一串**槽位而不是一个:
 * 首尾帧的那一串长度恒为 1,控件长得和以前一模一样。
 */

import type { MessageKey } from "@/app/messages";

/** 与后端 ai/providers/base.SOURCE_ROLES 同名。多一种要两边一起加(契约在描述符里)。 */
export const SOURCE_ROLES = [
  "first_frame",
  "last_frame",
  "reference_image",
  "reference_video",
  "reference_audio",
  "source_video",
  "first_clip",
] as const;
export type SourceRole = (typeof SOURCE_ROLES)[number];

/** 一个槽位里放着什么:要么是素材库里的一份,要么是一条外链,两者互斥。 */
export interface FrameSlot {
  url: string;
  assetId: string;
  assetName: string;
}

export const EMPTY_SLOT: FrameSlot = { url: "", assetId: "", assetName: "" };

/** 一个角色下挂着的全部槽位。 */
export type FrameSlots = Record<SourceRole, FrameSlot[]>;

interface RoleCopy {
  label: MessageKey;
  upload: MessageKey;
  uploading: MessageKey;
  urlLabel: MessageKey;
  /** 文件选择器收什么。参考视频/音频不是图片,收 image/* 会让用户在系统面板里一个文件都点不亮。 */
  accept: string;
}

/** 每种角色在界面上怎么称呼。控件本身是同一个。 */
export const ROLE_COPY: Record<SourceRole, RoleCopy> = {
  first_frame: {
    label: "genFirstFrame",
    upload: "genFirstFrameUpload",
    uploading: "genFirstFrameUploading",
    urlLabel: "genFirstFrameUrl",
    accept: "image/*",
  },
  last_frame: {
    label: "genLastFrame",
    upload: "genLastFrameUpload",
    uploading: "genLastFrameUploading",
    urlLabel: "genLastFrameUrl",
    accept: "image/*",
  },
  reference_image: {
    label: "genReferenceImage",
    upload: "genReferenceImageUpload",
    uploading: "genReferenceImageUploading",
    urlLabel: "genReferenceImageUrl",
    accept: "image/*",
  },
  reference_video: {
    label: "genReferenceVideo",
    upload: "genReferenceVideoUpload",
    uploading: "genReferenceVideoUploading",
    urlLabel: "genReferenceVideoUrl",
    accept: "video/*",
  },
  reference_audio: {
    label: "genReferenceAudio",
    upload: "genReferenceAudioUpload",
    uploading: "genReferenceAudioUploading",
    urlLabel: "genReferenceAudioUrl",
    accept: "audio/*",
  },
  source_video: {
    label: "genSourceVideo",
    upload: "genSourceVideoUpload",
    uploading: "genSourceVideoUploading",
    urlLabel: "genSourceVideoUrl",
    accept: "video/*",
  },
  first_clip: {
    label: "genFirstClip",
    upload: "genFirstClipUpload",
    uploading: "genFirstClipUploading",
    urlLabel: "genFirstClipUrl",
    accept: "video/*",
  },
};

/** 这个槽位是空的吗 —— 素材和外链都没有。 */
export function isEmptySlot(slot: FrameSlot): boolean {
  return !slot.assetId && !slot.url.trim();
}

/** 某个角色现在实际挂了几份。灰不灰另一组、还能不能再加一份,都看它。 */
export function filledCount(frames: FrameSlots, role: SourceRole): number {
  return frames[role].filter((slot) => !isEmptySlot(slot)).length;
}

/** 提交时,把非空的槽位翻成接口要的 [{asset_id, role}]。外链走 parameters 的 <role>_url。 */
export function sourceAssetsFrom(
  frames: FrameSlots,
  supported: (role: SourceRole) => boolean,
): { asset_id: string; role: SourceRole }[] {
  return SOURCE_ROLES.filter(supported).flatMap((role) =>
    frames[role].filter((slot) => slot.assetId).map((slot) => ({ asset_id: slot.assetId, role })),
  );
}

/**
 * 外链那一半:填了 url 的槽位变成 `first_frame_url` 这样的参数。
 *
 * **一个角色多条外链时发数组** —— 后端 ai/providers/base.source_values 两种都接。发成
 * 逗号拼的字符串会被当成一条打不开的地址,而那时任务已经提交了。
 */
export function frameUrlParameters(
  frames: FrameSlots,
  supported: (role: SourceRole) => boolean,
): Record<string, string | string[]> {
  const params: Record<string, string | string[]> = {};
  for (const role of SOURCE_ROLES) {
    if (!supported(role)) continue;
    const urls = frames[role].map((slot) => slot.url.trim()).filter(Boolean);
    if (urls.length === 1) params[`${role}_url`] = urls[0];
    else if (urls.length > 1) params[`${role}_url`] = urls;
  }
  return params;
}

export function emptyFrames(): FrameSlots {
  return {
    first_frame: [{ ...EMPTY_SLOT }],
    last_frame: [{ ...EMPTY_SLOT }],
    reference_image: [{ ...EMPTY_SLOT }],
    reference_video: [{ ...EMPTY_SLOT }],
    reference_audio: [{ ...EMPTY_SLOT }],
    source_video: [{ ...EMPTY_SLOT }],
    first_clip: [{ ...EMPTY_SLOT }],
  };
}

/** 换一个槽位的内容;顺手把末尾多出来的空槽收掉,只留一个。 */
export function withSlot(slots: FrameSlot[], index: number, next: FrameSlot): FrameSlot[] {
  const updated = slots.map((slot, i) => (i === index ? next : slot));
  const filled = updated.filter((slot) => !isEmptySlot(slot));
  return filled.length === updated.length ? updated : [...filled, { ...EMPTY_SLOT }];
}
