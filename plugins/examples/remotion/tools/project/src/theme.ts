/**
 * 画面尺寸与配色。讲解视频和自定义动画共用。
 *
 * 版式按「短边 = 1080」设计,再用 `unit` 等比缩放 —— 16:9、9:16、1:1 三种比例共用一套数值,
 * 竖屏不必另写一份。
 */

export type Aspect = "16:9" | "9:16" | "1:1";
export type ThemeName = "light" | "dark";

export const SIZES: Record<Aspect, { width: number; height: number }> = {
  "16:9": { width: 1920, height: 1080 },
  "9:16": { width: 1080, height: 1920 },
  "1:1": { width: 1080, height: 1080 },
};

export type Palette = {
  background: string;
  backgroundEdge: string;
  grid: string;
  text: string;
  muted: string;
  card: string;
  cardBorder: string;
  accent: string;
  accentSoft: string;
  /** 背景左上那一团光。比 accentSoft 淡:它铺得大,浓了在浅色底上像一块污渍。 */
  glow: string;
};

/** 用户给的强调色只认 #RRGGBB;其余一律回到默认,免得一个拼错的颜色把整段视频染坏。 */
export function accentOf(raw: unknown): string {
  return typeof raw === "string" && /^#[0-9a-fA-F]{6}$/.test(raw) ? raw : "#3B82F6";
}

function withAlpha(hex: string, alpha: number): string {
  const value = Number.parseInt(hex.slice(1), 16);
  return `rgba(${(value >> 16) & 255}, ${(value >> 8) & 255}, ${value & 255}, ${alpha})`;
}

export function palette(theme: ThemeName, accent: string): Palette {
  return theme === "light"
    ? {
        background: "#F7F8FA", backgroundEdge: "#E9ECF1", grid: "rgba(20, 30, 50, 0.07)",
        text: "#141821", muted: "#5B6474", card: "#FFFFFF", cardBorder: "rgba(20, 30, 50, 0.10)",
        accent, accentSoft: withAlpha(accent, 0.12), glow: withAlpha(accent, 0.06),
      }
    : {
        background: "#0F1217", backgroundEdge: "#171B22", grid: "rgba(255, 255, 255, 0.05)",
        text: "#F1F3F6", muted: "#9AA3B2", card: "#1A1F27", cardBorder: "rgba(255, 255, 255, 0.08)",
        accent, accentSoft: withAlpha(accent, 0.18), glow: withAlpha(accent, 0.14),
      };
}

/** 系统自带的中文字体排在前面:渲染用的是本机浏览器,不下载网络字体(离线也要能出片)。 */
export const SANS =
  '"PingFang SC", "Hiragino Sans GB", "Microsoft YaHei", "Noto Sans CJK SC", "Source Han Sans SC", system-ui, sans-serif';
export const MONO = '"SF Mono", "JetBrains Mono", Menlo, Consolas, "Noto Sans Mono CJK SC", monospace';
