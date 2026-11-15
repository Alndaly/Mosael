/** @vitest-environment jsdom */
import React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { expect, it } from "vitest";

import { PreferencesProvider } from "@/app/preferences";
import { ToolResultCard, detectShape } from "@/features/agent/toolResultShapes";

/**
 * `listen_to_audio` 的结果(ADR 0103)按形状认出来,画成「每段:关键数 + 带时间点的问题 + 频谱图」,
 * 两段以上末尾写两两的差别。没认出来的话它会掉进通用的键值摘要 —— 「listening 2 项」,问题一条都看不见。
 */

const report = (id: string, name: string, findings: unknown[]) => ({
  asset_id: id,
  name,
  seconds: 22,
  requested: { start: 0, end: null },
  loudness: { integrated: -15.8, true_peak: 0.3, range_lu: 8.3 },
  rhythm: { bpm: 118.6, steadiness: 0.69 },
  timbre: { pitch_hz: null, voiced_ratio: 0.1 },
  findings,
});

const value = {
  listening: [
    report("a", "第一版 BGM", [
      { kind: "dropouts", severity: "high", message: "中途断了 3 次,最长 0.5 秒", at: [1.24, 7.92] },
    ]),
    report("b", "第二版 BGM", []),
  ],
  comparison: [
    { a: "a", b: "b", brightness_ratio: 0.91, pitch_semitones: null, loudness_diff_lu: 2.2, timbre_distance: 0.81 },
  ],
  image_views: ["第一版 BGM", "第二版 BGM"],
};

it("认成「听」的结果:问题带时间点,没问题的那段说没量出来,末尾是两两的差别,每段一张频谱图", () => {
  expect(detectShape(value)).toBe("listening");
  render(
    <QueryClientProvider client={new QueryClient()}>
      <PreferencesProvider>
        <ToolResultCard value={value} />
      </PreferencesProvider>
    </QueryClientProvider>,
  );
  expect(screen.getByText("第一版 BGM")).toBeTruthy();
  expect(screen.getByText(/中途断了 3 次/).textContent).toContain("0:01.2");
  expect(screen.getByText(/中途断了 3 次/).textContent).toContain("0:07.9");
  expect(screen.getAllByText(/LUFS/).length).toBe(2);
  expect(screen.getByText("第一版 BGM → 第二版 BGM")).toBeTruthy();
  const pictures = screen.getAllByRole("img");
  expect(pictures).toHaveLength(2);
  expect(pictures[0].getAttribute("src")).toContain("/api/assets/a/spectrogram");
});
