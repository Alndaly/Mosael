/**
 * 生成面板里那些「带角色的输入素材」:首帧、尾帧、参考图、参考视频、参考音频、蒙版……
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
  "driving_audio",
  "mask",
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
  driving_audio: {
    label: "genDrivingAudio",
    upload: "genDrivingAudioUpload",
    uploading: "genDrivingAudioUploading",
    urlLabel: "genDrivingAudioUrl",
    accept: "audio/*",
  },
  first_clip: {
    label: "genFirstClip",
    upload: "genFirstClipUpload",
    uploading: "genFirstClipUploading",
    urlLabel: "genFirstClipUrl",
    accept: "video/*",
  },
  mask: {
    label: "genMask",
    upload: "genMaskUpload",
    uploading: "genMaskUploading",
    urlLabel: "genMaskUrl",
    accept: "image/*",
  },
};

/**
 * 一个角色收**哪一类**素材。`ROLE_COPY` 的 `accept` 就是这件事(文件选择器收什么),这里只是把它说成
 * 三个词 —— 画板按它给上游素材找槽位,工作流检查器按它判「引用即发送并进来的这一份,是不是这个角色
 * 要的那类素材」。和后端 `descriptors/shared.SOURCE_ROLE_MEDIA` 是同一份判断。
 */
export function roleMedia(role: string): "image" | "video" | "audio" {
  const accept = (ROLE_COPY as Record<string, RoleCopy | undefined>)[role]?.accept ?? "image/*";
  if (accept.startsWith("video/")) return "video";
  if (accept.startsWith("audio/")) return "audio";
  return "image";
}

/** 这个槽位是空的吗 —— 素材和外链都没有。 */
/**
 * 一行素材槽分几列 —— **一份就占满整行**,最多三份。真控件(ai-studio/FrameSlotField)和表单预览
 * (plugins/appForm/PreviewPanel)都从这里拿:预览要是自己定一套(比如 auto-fill + 88px 一格),
 * 一份素材在预览里就缩成一个小方块,而用的人真正看到的是铺满整行的那一格 —— 预览的意义正是"看到的就是这样"。
 */
export function slotColumns(count: number): string {
  return `repeat(${Math.min(Math.max(count, 1), 3)}, minmax(0, 1fr))`;
}

/** 空格子里**要写出来的那个名字** —— 命名链的最后一段,取不到就往回落,不回落到空。
 *
 * 维护者截图(暗色主题:「快速去水印」那张表单的参考图那一格):**一个虚线框加一个加号,没有名字**,
 * 而首/尾帧那两格写着「首帧」「Optional Load Image #127」。这一格的名字此前只有**一条**来源 ——
 * 描述符的 `source_labels`,于是那条链断在哪儿,哪儿就是一个纯图标格,而面板上别的每一格都有字。
 *
 * 链子本身没坏,是**它本来就会缺**:插件只在自己的表单上给每个槽位都报名字,缺省的表单只在"名字说得出
 * 东西"时才报(`Form.slot_labels`:一个角色一格、节点又没起过名就不报),连起来的模型这一格就是没有名字。
 * 界面上再撞一次(表单项的 key 认得出的角色、但描述符没给这一格的名字)就是截图里那一格。
 *
 * 回落的顺序就是既有的那几套文案,这里**不发明**新的说法:
 *
 * 1. 模型给这一格的名字(`source_labels[i]`,比如「加载图像 #15」);
 * 2. 这一格自己是「上传」那一条路时的说法(蒙版那一格并排两格:「上传」/「画一张」);
 * 3. 角色名(`ROLE_COPY` 的 `label`:参考图、蒙版、首帧……)—— 同一份文案就在上面那行角色标题里
 *    (见 `ai-studio/FrameSlotField` 的表头),读屏念的、悬停说明里写的也一直是它。
 *
 * 真面板(ai-studio/FrameSlotField)和表单预览(plugins/appForm/PreviewPanel)都走这一条链 ——
 * 和 `slotColumns` 一样,是两侧共用的**判据**,不是某一侧的画法。
 */
export function slotName(role: SourceRole, names: string[], index: number, t: (key: MessageKey) => string, uploadName?: MessageKey): string {
  const copy = ROLE_COPY[role];
  return names[index] || (uploadName ? t(uploadName) : "") || t(copy.label);
}

export function isEmptySlot(slot: FrameSlot): boolean {
  return !slot.assetId && !slot.url.trim();
}

/** 某个角色现在实际挂了几份。灰不灰另一组、还能不能再加一份,都看它。 */
export function filledCount(frames: FrameSlots, role: SourceRole): number {
  return frames[role].filter((slot) => !isEmptySlot(slot)).length;
}

/**
 * 通用那一栏(没有精简表单的模型、工作流的「完整工作流」入口)摆素材角色的先后。
 *
 * 和 SOURCE_ROLES 是**同一组角色、换个次序**(测试钉着两者一一对应):拿现成片子当输入的
 * 和首尾帧在上面,参考素材挨在一起,蒙版排最后、紧挨着它要改的那一组(ADR 0056 决定 2)。
 */
export const SOURCE_PANEL_ORDER: readonly SourceRole[] = [
  "first_frame",
  "last_frame",
  "source_video",
  "first_clip",
  "driving_audio",
  "reference_image",
  "reference_video",
  "reference_audio",
  "mask",
];

/**
 * 面板上画哪几格素材 —— **和提交时发哪几格是同一个判据**(`supported`,即描述符声明了这个角色)。
 *
 * 此前通用那一栏按模型种类手列角色(图像只列参考图、视频列首尾帧 / 输入 / 参考),而提交那一半
 * (`sourceAssetsFrom`)按 SOURCE_ROLES 全量发:描述符声明了、手列里却没有的角色(工作流完整入口的
 * 蒙版)就**画不出来,也就填不进去**,精简表单那一栏却能填 —— 同一个模型两个入口两种结果(ADR 0057)。
 */
export function panelSourceRoles(supported: (role: SourceRole) => boolean): SourceRole[] {
  return SOURCE_PANEL_ORDER.filter(supported);
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
    driving_audio: [{ ...EMPTY_SLOT }],
    mask: [{ ...EMPTY_SLOT }],
  };
}

/** 换一个槽位的内容;顺手把末尾多出来的空槽收掉,只留一个。 */
export function withSlot(slots: FrameSlot[], index: number, next: FrameSlot): FrameSlot[] {
  const updated = slots.map((slot, i) => (i === index ? next : slot));
  const filled = updated.filter((slot) => !isEmptySlot(slot));
  return filled.length === updated.length ? updated : [...filled, { ...EMPTY_SLOT }];
}
