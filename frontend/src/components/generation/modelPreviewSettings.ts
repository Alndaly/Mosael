import { useSyncExternalStore } from "react";

/**
 * 模型预览图怎么显示(ADR 0038 §9):两组设置,**记在这台电脑上**(看场合的事,不跟着账号走)。
 *
 * - **预览图**:清晰 / 轻度模糊 / 重度模糊 / 不显示(只画按目录分的图标);
 * - **NSFW 预览**:照常(和别的预览图一样)/ 模糊 / 不显示 —— 只管判成 NSFW 的那些(判断见宿主的 domain/model_library)。
 *
 * 两组独立生效、取更严的那一档:「预览图清晰 + NSFW 不显示」就是平常的图照常看、NSFW 的只剩图标。模糊的悬停或点开单张
 * 能临时看清;不显示的不去取图,详情页里点「显示这一张」才取。
 *
 * 模型库(网格、列表、详情)、生成表单里选模型 / LoRA 的下拉、工作台的模型库面板都读这一份;在任何一处改了,
 * 别处马上跟着变(同一个窗口里发事件,别的窗口靠 storage 事件)。
 */

export const PREVIEW_LEVELS = ["clear", "light", "heavy", "hidden"] as const;
export type PreviewLevel = (typeof PREVIEW_LEVELS)[number];
export const NSFW_MODES = ["show", "blur", "hidden"] as const;
export type NsfwMode = (typeof NSFW_MODES)[number];
export type ModelPreviewSettings = { level: PreviewLevel; nsfw: NsfwMode };

/** 缺省:平常的预览图清晰(糊着会让第一次打开的人以为图坏了),NSFW 的模糊。 */
export const DEFAULT_PREVIEW_SETTINGS: ModelPreviewSettings = { level: "clear", nsfw: "blur" };
export const MODEL_PREVIEWS_KEY = "mosael:model-previews";
const CHANGED = "mosael:model-previews-changed";

let cachedRaw: string | null | undefined;
let cached: ModelPreviewSettings = DEFAULT_PREVIEW_SETTINGS;
let sessionOverride: ModelPreviewSettings | null = null;

function parse(raw: string | null): ModelPreviewSettings {
  if (!raw) return DEFAULT_PREVIEW_SETTINGS;
  try {
    const value = JSON.parse(raw) as Partial<ModelPreviewSettings>;
    return {
      level: PREVIEW_LEVELS.includes(value.level as PreviewLevel) ? (value.level as PreviewLevel) : DEFAULT_PREVIEW_SETTINGS.level,
      nsfw: NSFW_MODES.includes(value.nsfw as NsfwMode) ? (value.nsfw as NsfwMode) : DEFAULT_PREVIEW_SETTINGS.nsfw,
    };
  } catch {
    return DEFAULT_PREVIEW_SETTINGS;
  }
}

/** 现在的设置。按存着的原文记忆:同一份原文交回同一个对象(useSyncExternalStore 要它稳定)。 */
export function readModelPreviewSettings(): ModelPreviewSettings {
  if (sessionOverride) return sessionOverride;
  let raw: string | null = null;
  try {
    raw = localStorage.getItem(MODEL_PREVIEWS_KEY);
  } catch {
    return DEFAULT_PREVIEW_SETTINGS;
  }
  if (raw !== cachedRaw) {
    cachedRaw = raw;
    cached = parse(raw);
  }
  return cached;
}

export function setModelPreviewSettings(next: ModelPreviewSettings): void {
  try {
    localStorage.setItem(MODEL_PREVIEWS_KEY, JSON.stringify(next));
    sessionOverride = null;
  } catch {
    // 隐私模式 / 没有 storage:这次会话里照样生效
    sessionOverride = next;
  }
  window.dispatchEvent(new Event(CHANGED));
}

function subscribe(notify: () => void) {
  const storage = (event: StorageEvent) => {
    if (!event.key || event.key === MODEL_PREVIEWS_KEY) notify();
  };
  window.addEventListener(CHANGED, notify);
  window.addEventListener("storage", storage);
  return () => {
    window.removeEventListener(CHANGED, notify);
    window.removeEventListener("storage", storage);
  };
}

export function useModelPreviewSettings(): [ModelPreviewSettings, (next: ModelPreviewSettings) => void] {
  return [useSyncExternalStore(subscribe, readModelPreviewSettings, () => DEFAULT_PREVIEW_SETTINGS), setModelPreviewSettings];
}

/**
 * 那台服务器上没有预览图、用 Civitai 的示例图时挑哪一张:NSFW「照常」时要作者排在最前的那张(最能代表这个模型),
 * 模糊 / 不显示时要分级最低的那张 —— 省得一张本来能看的预览图因为挑了成人的那张而被藏起来。
 */
export function previewPick(settings: ModelPreviewSettings): "safest" | "cover" {
  return settings.nsfw === "show" ? "cover" : "safest";
}

/** 一张预览图怎么画:就是四档里的一档。 */
export type PreviewTreatment = PreviewLevel;

const STRICTNESS: Record<PreviewTreatment, number> = { clear: 0, light: 1, heavy: 2, hidden: 3 };
const NSFW_TREATMENT: Record<NsfwMode, PreviewTreatment> = { show: "clear", blur: "heavy", hidden: "hidden" };

/** 按两组设置和「是不是 NSFW」定一张预览图怎么画:平常的按「预览图」那一档,NSFW 的再和「NSFW 预览」那一档取更严的。 */
export function previewTreatment(settings: ModelPreviewSettings, flagged: boolean): PreviewTreatment {
  const own = settings.level;
  if (!flagged) return own;
  const nsfw = NSFW_TREATMENT[settings.nsfw];
  return STRICTNESS[nsfw] > STRICTNESS[own] ? nsfw : own;
}

/**
 * 一次性迁移(启动时跑,见 lib/localMigrations):此前只有一个「模糊预览图」开关(`mosael:tab:model-library.blur`,
 * on / off,开着是重度模糊、悬停看清)。换成两组设置:开着 → 预览图「重度模糊」,关着 → 「清晰」,NSFW 那一组用缺省。
 * 已经有新设置的不覆盖;旧键一律删掉 —— 之后没有代码读它。
 */
export const LEGACY_BLUR_KEY = "mosael:tab:model-library.blur";

export function migrateModelPreviewBlur(storage: Storage): void {
  const old = storage.getItem(LEGACY_BLUR_KEY);
  if (old === null) return;
  if (storage.getItem(MODEL_PREVIEWS_KEY) === null && (old === "on" || old === "off")) {
    const migrated: ModelPreviewSettings = { ...DEFAULT_PREVIEW_SETTINGS, level: old === "on" ? "heavy" : "clear" };
    storage.setItem(MODEL_PREVIEWS_KEY, JSON.stringify(migrated));
  }
  storage.removeItem(LEGACY_BLUR_KEY);
}
