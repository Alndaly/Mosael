import { fontFileUrl, type Font } from "@/api/client";

/**
 * Registers every uploaded workspace font with the document as an @font-face, keyed by the
 * family name the backend read out of the file. That name is the contract between the two
 * renderers: the preview resolves it through CSS here, and export resolves the same name
 * through libass against the same file — so what you see is what gets burned in.
 */
export function FontFaces({ fonts }: { fonts: Font[] }) {
  if (fonts.length === 0) return null;
  const css = fonts
    .map(
      (font) =>
        `@font-face{font-family:${JSON.stringify(font.family)};` +
        `src:url(${JSON.stringify(fontFileUrl(font.id))});font-display:swap;}`,
    )
    .join("\n");
  return <style>{css}</style>;
}

/** The CSS stack to store for an uploaded font: its own family, then a generic so text still
    renders while the file loads (or if it later goes missing). */
export function uploadedFontStack(family: string): string {
  return `${JSON.stringify(family)}, sans-serif`;
}
