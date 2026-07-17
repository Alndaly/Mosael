import { describe, expect, it } from "vitest";

import {
  COLOR_PRESETS,
  matchColorPreset,
  presetColorPayload,
} from "@/features/editor/colorPresets";

describe("presetColorPayload", () => {
  it("spreads grade values and attaches curves when present", () => {
    const vivid = COLOR_PRESETS.find((p) => p.key === "vivid")!;
    const payload = presetColorPayload(vivid);
    expect(payload.saturation).toBe(0.3);
    expect(payload.curves).toBeUndefined();

    const cinematic = COLOR_PRESETS.find((p) => p.key === "cinematic")!;
    expect(presetColorPayload(cinematic).curves).toBeDefined();
  });
});

describe("matchColorPreset", () => {
  it("returns null for empty / custom color", () => {
    expect(matchColorPreset(undefined)).toBeNull();
    expect(matchColorPreset({})).toBeNull();
    expect(matchColorPreset({ saturation: 0.13 })).toBeNull(); // no preset uses 0.13
  });

  it("round-trips every preset through its own payload", () => {
    for (const preset of COLOR_PRESETS) {
      expect(matchColorPreset(presetColorPayload(preset))).toBe(preset.key);
    }
  });

  it("does not match when an undefined slider key is nudged off zero", () => {
    const warm = COLOR_PRESETS.find((p) => p.key === "warm")!;
    const payload = { ...presetColorPayload(warm), exposure: 0.2 };
    expect(matchColorPreset(payload)).toBeNull();
  });

  it("distinguishes cinematic (has curves) from a curve-stripped copy", () => {
    const cinematic = COLOR_PRESETS.find((p) => p.key === "cinematic")!;
    const stripped = presetColorPayload(cinematic);
    delete stripped.curves;
    expect(matchColorPreset(stripped)).toBeNull();
  });
});
