import type { MessageKey } from "@/app/messages";
import type { ShotBreakdown, ShotHint } from "@/api/domains/shots";
import { shotsOf } from "@/api/domains/shots";

/**
 * 镜头表上的字(ADR 0061 §5)。
 *
 * 三样东西,都是**后端给原词、界面翻成人话**:
 *
 * 1. **五张封闭词表的中文标签**(`domain/shots/vocab.py` 的 `SIZES` / `CATEGORIES` / `CAMERA_MOVES` /
 *    `TRANSITIONS` / `RHYTHMS`)。词表是封闭的,所以这里是「值 → 文案键」的**全表**,不是猜。
 *    界面上的语言跟着界面走:后端另有一份 zh/en(报告和提示词用),两份各自服务一处的读者。
 * 2. **对账提示的句子**(`hints[].kind`,12 种)。后端给出的是结构(`{shot,kind,field,value}`),
 *    人话在这里。
 * 3. **分镜稿的正文**:后端拼好的`storyboard_markdown`;它没有时(老的镜头表、只有机器那一半)
 *    用各镜自己的 `prompt` 拼一份,别让那颗按钮点了什么都不给。
 *
 * 认不出的值一律**原样显示**(表外的景别词、以后新加的 hint kind):宁可露出一个生词,也不吞掉。
 */

/** 五张封闭词表各自的字段名。 */
export type ShotField = "size" | "category" | "camera" | "transition_in" | "rhythm";

/** 值 → 文案键。键名把 `-` 写成 `_`(文案表的键只能是 `\w`)。 */
const VOCAB: Readonly<Record<ShotField, Readonly<Record<string, MessageKey>>>> = {
  size: {
    none: "shotSize_none",
    "extreme-wide": "shotSize_extreme_wide",
    wide: "shotSize_wide",
    "medium-wide": "shotSize_medium_wide",
    medium: "shotSize_medium",
    "medium-close": "shotSize_medium_close",
    close: "shotSize_close",
    "extreme-close": "shotSize_extreme_close",
  },
  category: {
    establishing: "shotCategory_establishing",
    subject: "shotCategory_subject",
    dialogue: "shotCategory_dialogue",
    reaction: "shotCategory_reaction",
    insert: "shotCategory_insert",
    pov: "shotCategory_pov",
    empty: "shotCategory_empty",
    product: "shotCategory_product",
    "text-card": "shotCategory_text_card",
    transition: "shotCategory_transition",
    archive: "shotCategory_archive",
  },
  camera: {
    static: "shotCamera_static",
    "push-in": "shotCamera_push_in",
    "pull-out": "shotCamera_pull_out",
    "zoom-in": "shotCamera_zoom_in",
    "zoom-out": "shotCamera_zoom_out",
    "pan-left": "shotCamera_pan_left",
    "pan-right": "shotCamera_pan_right",
    "tilt-up": "shotCamera_tilt_up",
    "tilt-down": "shotCamera_tilt_down",
    "truck-left": "shotCamera_truck_left",
    "truck-right": "shotCamera_truck_right",
    "pedestal-up": "shotCamera_pedestal_up",
    "pedestal-down": "shotCamera_pedestal_down",
    tracking: "shotCamera_tracking",
    arc: "shotCamera_arc",
    "whip-pan": "shotCamera_whip_pan",
    handheld: "shotCamera_handheld",
    shake: "shotCamera_shake",
    "rack-focus": "shotCamera_rack_focus",
    "micro-push": "shotCamera_micro_push",
    roll: "shotCamera_roll",
    drone: "shotCamera_drone",
  },
  transition_in: {
    cut: "shotTransition_cut",
    dissolve: "shotTransition_dissolve",
    "fade-in": "shotTransition_fade_in",
    "fade-out": "shotTransition_fade_out",
    whip: "shotTransition_whip",
    "match-cut": "shotTransition_match_cut",
    wipe: "shotTransition_wipe",
    morph: "shotTransition_morph",
  },
  rhythm: {
    hook: "shotRhythm_hook",
    setup: "shotRhythm_setup",
    build: "shotRhythm_build",
    beat: "shotRhythm_beat",
    turn: "shotRhythm_turn",
    payoff: "shotRhythm_payoff",
    breath: "shotRhythm_breath",
    close: "shotRhythm_close",
  },
};

/** 这一格说的是哪一样(提示里「{field}不在词表里」用)。 */
const FIELDS: Readonly<Record<string, MessageKey>> = {
  size: "shotField_size",
  category: "shotField_category",
  camera: "shotField_camera",
  transition_in: "shotField_transition",
  rhythm: "shotField_rhythm",
};

/** 14 种提示各一句人话(键):判画面那 12 种(`domain/shots/describe.py`)+ 分析抽帧那 2 种
 *  (`analysis/service.py` 的 `sheets_truncated` / `sheets_unavailable`)。** */
const HINTS: Readonly<Record<string, MessageKey>> = {
  unknown_word: "shotHint_unknown_word",
  camera_corrected: "shotHint_camera_corrected",
  static_but_moving: "shotHint_static_but_moving",
  thin_frame: "shotHint_thin_frame",
  flat_stretch: "shotHint_flat_stretch",
  batch_unreadable: "shotHint_batch_unreadable",
  batch_failed: "shotHint_batch_failed",
  not_judged: "shotHint_not_judged",
  not_described: "shotHint_not_described",
  truncated: "shotHint_truncated",
  no_hook: "shotHint_no_hook",
  payoff_without_setup: "shotHint_payoff_without_setup",
  sheets_truncated: "shotHint_sheets_truncated",
  sheets_unavailable: "shotHint_sheets_unavailable",
};

/** 这个词表里的值对应的文案键;表外(不该有,但以后可能加)返回 null,由调用方原样显示。 */
export function vocabKey(field: ShotField, value: string): MessageKey | null {
  return VOCAB[field]?.[value] ?? null;
}

/** 这一格叫什么:`size` → 「景别」。 */
export function shotFieldKey(field: string): MessageKey | null {
  return FIELDS[field] ?? null;
}

/**
 * 一条提示的一句话。值按 `{shot}` / `{field}` / `{kind}` / `{value}` 替进去 —— 文案表里的占位符,
 * 和 `docSavedAsNote` 那几条同一套写法。
 *
 * `kind` 认不出时给一句通用的(带上 kind 本身),不把提示闷掉。
 */
export function shotHintText(t: (key: MessageKey) => string, hint: ShotHint): string {
  const kind = hint.kind ?? "";
  const key = HINTS[kind];
  const fieldKey = shotFieldKey(hint.field ?? "");
  return (key ? t(key) : t("shotHint_other"))
    .replace("{kind}", kind)
    .replace("{shot}", hint.shot ?? "")
    .replace("{field}", fieldKey ? t(fieldKey) : (hint.field ?? ""))
    .replace("{value}", hint.value ?? "")
    .trim();
}

/**
 * 「复制分镜提示词」要复制的那份稿子:后端拼好的`storyboard_markdown`。
 *
 * 后端没给时(判画面之前、或者老数据)用各镜自己的 `prompt` 拼一份 —— 有哪几镜用哪几镜;
 * 一镜都没有 prompt 时给空串,那颗按钮就点不了(空了还能点等于骗人)。
 */
export function storyboardText(breakdown: Pick<ShotBreakdown, "storyboard_markdown" | "shots">): string {
  const made = (breakdown.storyboard_markdown ?? "").trim();
  if (made) return made;
  return shotsOf(breakdown)
    .map((shot) => ({ id: shot.id, prompt: (shot.prompt ?? "").trim() }))
    .filter((one) => one.prompt)
    .map((one) => `${one.id} ${one.prompt}`)
    .join("\n\n");
}
