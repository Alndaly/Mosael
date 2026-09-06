/** Local, bundled interface fonts. Media/subtitle fonts and timecode remain independent. */
const system = '-apple-system, BlinkMacSystemFont, "PingFang SC", "Microsoft YaHei", "Segoe UI", system-ui, sans-serif';
export const INTERFACE_FONTS = [
  { id: "default", label: "fontDefault", family: `"Inter Variable", ${system}` },
  { id: "system", label: "fontSystem", family: system },
  { id: "noto-sans", label: "fontNotoSans", family: `"Noto Sans SC Variable", ${system}` },
  { id: "noto-serif", label: "fontNotoSerif", family: '"Noto Serif SC Variable", "Songti SC", "SimSun", serif' },
  { id: "wenkai", label: "fontWenKai", family: `"LXGW WenKai Screen", ${system}` },
  { id: "space-grotesk", label: "fontSpaceGrotesk", family: `"Space Grotesk Variable", "Noto Sans SC Variable", ${system}` },
  { id: "newsreader", label: "fontNewsreader", family: '"Newsreader Variable", "Noto Serif SC Variable", "Songti SC", "SimSun", serif' },
  { id: "caveat", label: "fontCaveat", family: `"Caveat Variable", "LXGW WenKai Screen", ${system}` },
  { id: "kalam", label: "fontKalam", family: `"Kalam", "LXGW WenKai Screen", ${system}` },
] as const;
export type InterfaceFont = typeof INTERFACE_FONTS[number]["id"];
export function normalizeInterfaceFont(value: unknown): InterfaceFont {
  return INTERFACE_FONTS.find((font) => font.id === value)?.id ?? "default";
}

/** CSS is loaded on demand; Vite bundles every referenced WOFF2 for offline use. */
export function loadInterfaceFont(font: InterfaceFont): Promise<unknown> {
  if (font === "noto-sans") return import("@fontsource-variable/noto-sans-sc/index.css");
  if (font === "noto-serif") return import("@fontsource-variable/noto-serif-sc/index.css");
  if (font === "space-grotesk") return Promise.all([
    import("@fontsource-variable/space-grotesk/index.css"),
    loadInterfaceFont("noto-sans"),
  ]);
  if (font === "newsreader") return Promise.all([
    import("@fontsource-variable/newsreader/index.css"),
    loadInterfaceFont("noto-serif"),
  ]);
  if (font === "caveat") return import("@fontsource-variable/caveat/index.css");
  if (font === "kalam") return Promise.all([
    import("@fontsource/kalam/400.css"),
    import("@fontsource/kalam/700.css"),
  ]);
  return Promise.resolve();
}
