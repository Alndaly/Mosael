import { readFileSync } from "node:fs";

import { describe, expect, it } from "vitest";

const sidePanelSource = readFileSync(
  new URL("../src/sidepanel.tsx", import.meta.url),
  "utf8",
);
const selectSource = readFileSync(
  new URL("../src/components/ui/select.tsx", import.meta.url),
  "utf8",
);

describe("side panel form controls", () => {
  it("does not use browser-native form controls in the feature shell", () => {
    expect(sidePanelSource).not.toMatch(/<(select|option|input|button|textarea)\b/);
    expect(selectSource).toContain('@radix-ui/react-select');
  });

  it("keeps the transcript language selector visibly bordered", () => {
    const trigger = sidePanelSource.match(
      /<SelectTrigger className="([^"]+)" aria-label=\{t\("targetLanguage"\)\}/,
    );

    expect(trigger?.[1]).toContain("border-input");
    expect(trigger?.[1]).not.toContain("border-0");
    expect(trigger?.[1]).not.toContain("bg-transparent");
  });

  it("uses narrow-panel-safe layouts for long localized actions", () => {
    expect(sidePanelSource).toContain("grid grid-cols-1 gap-2 min-[440px]:grid-cols-2");
    expect(sidePanelSource).toContain("flex flex-col items-stretch gap-3 min-[430px]:flex-row");
    expect(sidePanelSource).not.toContain("grid grid-cols-2 gap-2");
  });

  it("does not show transcript-only controls in an empty or failed state", () => {
    expect(sidePanelSource).toMatch(/\{transcript \? \(\s*<div className="p-4 pb-2">/);
    expect(sidePanelSource).toMatch(/\{transcript \? \(\s*<div className="flex items-center gap-2/);
  });

  it("uses borders and flat color layers instead of shadows", () => {
    expect(sidePanelSource).not.toMatch(/shadow-(?:sm|md|lg|xl|2xl)/);
    expect(selectSource).not.toMatch(/shadow-(?:sm|md|lg|xl|2xl)/);
  });
});
