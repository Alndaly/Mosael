import { readFileSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

const css = readFileSync(join(import.meta.dirname, "tokens.css"), "utf8");

function block(selector: string): string {
  const escaped = selector.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const match = css.match(new RegExp(`${escaped} \\{([\\s\\S]*?)\\n\\}`));
  if (!match) throw new Error(`Missing ${selector} token block`);
  return match[1];
}

function token(source: string, name: string): string {
  const match = source.match(new RegExp(`--${name}:\\s*(#[0-9a-fA-F]{6})`));
  if (!match) throw new Error(`Missing or non-hex --${name}`);
  return match[1];
}

function luminance(hex: string): number {
  const channels = [1, 3, 5].map((offset) => Number.parseInt(hex.slice(offset, offset + 2), 16) / 255);
  const linear = channels.map((channel) => channel <= 0.04045 ? channel / 12.92 : ((channel + 0.055) / 1.055) ** 2.4);
  return 0.2126 * linear[0] + 0.7152 * linear[1] + 0.0722 * linear[2];
}

function contrast(a: string, b: string): number {
  const [light, dark] = [luminance(a), luminance(b)].sort((x, y) => y - x);
  return (light + 0.05) / (dark + 0.05);
}

describe("semantic status colors", () => {
  it("exports warning and keeps success/warning readable on light and dark popovers", () => {
    expect(css).toContain("--color-warning: var(--warning)");

    for (const theme of [block(":root"), block(".dark")]) {
      const surface = token(theme, "popover");
      expect(contrast(token(theme, "success"), surface)).toBeGreaterThanOrEqual(4.5);
      expect(contrast(token(theme, "warning"), surface)).toBeGreaterThanOrEqual(4.5);
    }
  });

  it("keeps Open Studio text, actions and keyboard focus readable in both themes", () => {
    for (const theme of [block(":root"), block(".dark")]) {
      for (const [ink, paper] of [
        ["foreground", "background"], ["muted-foreground", "card"],
        ["primary-foreground", "primary"], ["accent-foreground", "accent"],
        ["destructive-foreground", "destructive"],
      ]) expect(contrast(token(theme, ink), token(theme, paper)), `${ink} on ${paper}`).toBeGreaterThanOrEqual(4.5);
      for (const edge of ["ring", "input"])
        expect(contrast(token(theme, edge), token(theme, "field")), edge).toBeGreaterThanOrEqual(3);
    }
  });

});
