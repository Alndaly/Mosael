export type MaskShape = "none" | "rounded" | "circle";

export interface ClipAppearance {
  mask: { shape: MaskShape; radius: number };
  shadow: {
    enabled: boolean;
    color: string;
    opacity: number;
    blur: number;
    offsetX: number;
    offsetY: number;
  };
}

export const DEFAULT_CLIP_APPEARANCE: ClipAppearance = {
  mask: { shape: "none", radius: 0 },
  shadow: { enabled: false, color: "#000000", opacity: 0.4, blur: 24, offsetX: 0, offsetY: 12 },
};

const record = (value: unknown): Record<string, unknown> =>
  value != null && typeof value === "object" && !Array.isArray(value) ? (value as Record<string, unknown>) : {};

const number = (value: unknown, fallback: number, min: number, max: number): number =>
  typeof value === "number" && Number.isFinite(value) ? Math.max(min, Math.min(max, value)) : fallback;

/** Defensive mirror of backend ``_read_appearance``. Project JSON is never trusted directly. */
export function readClipAppearance(effects: unknown): ClipAppearance {
  const appearance = record(record(effects).appearance);
  const mask = record(appearance.mask);
  const rawShape = mask.shape;
  const shape: MaskShape = rawShape === "rounded" || rawShape === "circle" ? rawShape : "none";
  const shadow = record(appearance.shadow);
  const rawColor = typeof shadow.color === "string" ? shadow.color : "";
  return {
    mask: { shape, radius: number(mask.radius, 0, 0, 0.5) },
    shadow: {
      enabled: shadow.enabled === true,
      color: /^#[0-9a-f]{6}$/i.test(rawColor) ? rawColor.toLowerCase() : "#000000",
      opacity: number(shadow.opacity, 0.4, 0, 1),
      blur: number(shadow.blur, 24, 0, 200),
      offsetX: number(shadow.offset_x, 0, -500, 500),
      offsetY: number(shadow.offset_y, 12, -500, 500),
    },
  };
}

/** Serialize the UI model using the snake_case persisted/render contract. */
export function clipAppearancePayload(value: ClipAppearance): Record<string, unknown> {
  return {
    mask: value.mask,
    shadow: {
      enabled: value.shadow.enabled,
      color: value.shadow.color,
      opacity: value.shadow.opacity,
      blur: value.shadow.blur,
      offset_x: value.shadow.offsetX,
      offset_y: value.shadow.offsetY,
    },
  };
}
