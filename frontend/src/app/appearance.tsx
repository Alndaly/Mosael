import React from "react";

/**
 * Opt-in appearance customization: an app-wide background (gradient preset or a
 * user image) plus adjustable surface transparency and frosted-glass blur. All
 * per-device (localStorage), applied as CSS variables + a `data-appearance`
 * flag on <html>; the glass token overrides live in styles.css. When the
 * background is "none" the app stays exactly as-is (flat, opaque).
 */

export type BackgroundKind = "none" | "preset" | "image";

export interface AppearanceState {
  kind: BackgroundKind;
  preset: string;
  surfaceOpacity: number; // 0.35–1  — how opaque panels stay over the background
  blur: number; // 0–32 px — frosted-glass intensity
  dim: number; // 0–0.75  — darken the background for text contrast
}

export interface BackgroundPreset {
  id: string;
  label: string;
  css: string;
}

export const BACKGROUND_PRESETS: BackgroundPreset[] = [
  { id: "aurora", label: "极光", css: "linear-gradient(135deg, #1e3a8a 0%, #6d28d9 45%, #0891b2 100%)" },
  { id: "dusk", label: "暮色", css: "linear-gradient(160deg, #fb7185 0%, #f59e0b 50%, #7c3aed 100%)" },
  { id: "graphite", label: "石墨", css: "linear-gradient(180deg, #232a36 0%, #0f131a 100%)" },
  { id: "mist", label: "晨雾", css: "linear-gradient(135deg, #a5b4fc 0%, #f5d0fe 55%, #fbcfe8 100%)" },
  { id: "forest", label: "松林", css: "linear-gradient(150deg, #064e3b 0%, #065f46 45%, #0f766e 100%)" },
];

const PARAMS_KEY = "mibu.appearance";
const IMAGE_KEY = "mibu.appearance.image";

const DEFAULTS: AppearanceState = { kind: "none", preset: "aurora", surfaceOpacity: 0.72, blur: 16, dim: 0.28 };

type AppearanceContextValue = AppearanceState & {
  image: string | null;
  update: (patch: Partial<AppearanceState>) => void;
  setImage: (dataUrl: string) => void;
  clearImage: () => void;
  reset: () => void;
};

const AppearanceContext = React.createContext<AppearanceContextValue | null>(null);

export function AppearanceProvider({ children }: { children: React.ReactNode }) {
  const [state, setState] = React.useState<AppearanceState>(readParams);
  const [image, setImageState] = React.useState<string | null>(readImage);

  // Apply to the document root whenever anything changes.
  React.useEffect(() => {
    const root = document.documentElement;
    const active = state.kind !== "none" && !(state.kind === "image" && !image);
    if (active) root.dataset.appearance = "glass";
    else delete root.dataset.appearance;

    root.style.setProperty("--app-surface-opacity", String(state.surfaceOpacity));
    root.style.setProperty("--app-blur", `${state.blur}px`);
    root.style.setProperty("--app-bg-dim", String(state.dim));

    const bgImage =
      state.kind === "image" && image
        ? `url("${image}")`
        : state.kind === "preset"
          ? (BACKGROUND_PRESETS.find((p) => p.id === state.preset) ?? BACKGROUND_PRESETS[0]).css
          : "none";
    root.style.setProperty("--app-bg-image", bgImage);

    try {
      window.localStorage.setItem(PARAMS_KEY, JSON.stringify(state));
    } catch {
      /* 隐私模式:退化为内存态 */
    }
  }, [state, image]);

  const value = React.useMemo<AppearanceContextValue>(
    () => ({
      ...state,
      image,
      update: (patch) => setState((prev) => ({ ...prev, ...patch })),
      setImage: (dataUrl) => {
        setImageState(dataUrl);
        setState((prev) => ({ ...prev, kind: "image" }));
        try {
          window.localStorage.setItem(IMAGE_KEY, dataUrl);
        } catch {
          /* 图片过大或隐私模式:仅内存生效,刷新后回退 */
        }
      },
      clearImage: () => {
        setImageState(null);
        setState((prev) => ({ ...prev, kind: prev.kind === "image" ? "none" : prev.kind }));
        try {
          window.localStorage.removeItem(IMAGE_KEY);
        } catch {
          /* ignore */
        }
      },
      reset: () => {
        setState(DEFAULTS);
        setImageState(null);
        try {
          window.localStorage.removeItem(IMAGE_KEY);
        } catch {
          /* ignore */
        }
      },
    }),
    [state, image],
  );

  return (
    <AppearanceContext.Provider value={value}>
      <div className="app-bg" aria-hidden />
      {children}
    </AppearanceContext.Provider>
  );
}

export function useAppearance() {
  const value = React.useContext(AppearanceContext);
  if (!value) throw new Error("useAppearance must be used inside AppearanceProvider");
  return value;
}

/** Downscale + JPEG-compress a picked image so it fits localStorage comfortably
 * (a wallpaper at 1920px q0.8 is a few hundred KB). Returns a data URL. */
export function compressImageFile(file: File, maxDimension = 1920, quality = 0.8): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onerror = () => reject(new Error("读取图片失败"));
    reader.onload = () => {
      const img = new Image();
      img.onerror = () => reject(new Error("无法解析图片"));
      img.onload = () => {
        const scale = Math.min(1, maxDimension / Math.max(img.width, img.height));
        const w = Math.round(img.width * scale);
        const h = Math.round(img.height * scale);
        const canvas = document.createElement("canvas");
        canvas.width = w;
        canvas.height = h;
        const ctx = canvas.getContext("2d");
        if (!ctx) return reject(new Error("画布不可用"));
        ctx.drawImage(img, 0, 0, w, h);
        resolve(canvas.toDataURL("image/jpeg", quality));
      };
      img.src = reader.result as string;
    };
    reader.readAsDataURL(file);
  });
}

function readParams(): AppearanceState {
  if (typeof window === "undefined") return DEFAULTS;
  try {
    const parsed = JSON.parse(window.localStorage.getItem(PARAMS_KEY) ?? "{}") as Partial<AppearanceState>;
    return {
      kind: parsed.kind === "preset" || parsed.kind === "image" ? parsed.kind : "none",
      preset: typeof parsed.preset === "string" ? parsed.preset : DEFAULTS.preset,
      surfaceOpacity: clamp(parsed.surfaceOpacity, 0.35, 1, DEFAULTS.surfaceOpacity),
      blur: clamp(parsed.blur, 0, 32, DEFAULTS.blur),
      dim: clamp(parsed.dim, 0, 0.75, DEFAULTS.dim),
    };
  } catch {
    return DEFAULTS;
  }
}

function readImage(): string | null {
  if (typeof window === "undefined") return null;
  try {
    return window.localStorage.getItem(IMAGE_KEY);
  } catch {
    return null;
  }
}

function clamp(value: unknown, min: number, max: number, fallback: number): number {
  return typeof value === "number" && Number.isFinite(value) ? Math.min(max, Math.max(min, value)) : fallback;
}
