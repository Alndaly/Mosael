/** @vitest-environment jsdom */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import React from "react";
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";

vi.mock("@/app/preferences", () => ({
  useI18n: () => (key: string) => key,
  usePreferences: () => ({ locale: "zh-CN" }),
}));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn(), info: vi.fn() } }));
const saved: Array<{ name: string }> = [];
vi.mock("@/lib/download", () => ({ saveBlobToDisk: (_blob: Blob, name: string) => saved.push({ name }) }));

import { isSubtitleFile } from "@/api/client";
import { SubtitleFiles } from "@/features/editor/SubtitleFiles";

beforeAll(() => {
  Object.assign(Element.prototype, {
    hasPointerCapture: () => false,
    setPointerCapture: () => {},
    releasePointerCapture: () => {},
    scrollIntoView: () => {},
  });
});
const originalFetch = globalThis.fetch;
afterEach(() => {
  globalThis.fetch = originalFetch;
  saved.length = 0;
});

const cue = (id: string, text: string) => ({
  id, track_id: "s1", asset_id: null, timeline_start: 0, src_in: 0, src_out: 2, speed: 1, text_override: text,
});
const sequence = {
  id: "seq", name: "访谈", workspace_id: "w", revision: 1,
  tracks: [{ id: "s1", kind: "subtitle", name: "S1", position: 2, clips: [cue("c1", "你好\nHello")] }],
} as never;

function renderFiles(onImport = vi.fn()) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <SubtitleFiles sequence={sequence} onImport={onImport} />
    </QueryClientProvider>,
  );
  return onImport;
}

describe("字幕文件", () => {
  it("导入默认落到一条新字幕轨,不碰已有的", async () => {
    const user = userEvent.setup();
    const onImport = renderFiles();
    await user.click(screen.getByRole("button", { name: /subtitleFileImport/ }));
    const file = new File(["1\n00:00:01,000 --> 00:00:02,000\n你好\n"], "a.srt", { type: "text/plain" });
    await user.upload(screen.getByLabelText("subtitleFileChoose"), file);
    expect(onImport).toHaveBeenCalledWith(file, {});
  });

  it("双语字幕导出时可以只写译文,请求带上轨道、格式和那一行", async () => {
    const urls: string[] = [];
    globalThis.fetch = vi.fn(async (input: RequestInfo | URL) => {
      urls.push(String(input));
      return new Response("WEBVTT\n", { status: 200 });
    }) as never;
    const user = userEvent.setup();
    renderFiles();
    await user.click(screen.getByRole("button", { name: /subtitleFileExport/ }));
    await user.click(screen.getByRole("combobox", { name: "subtitleFileFormat" }));
    await user.click(await screen.findByRole("option", { name: "WebVTT" }));
    await user.click(screen.getByRole("combobox", { name: "subtitleFileLine" }));
    await user.click(await screen.findByRole("option", { name: "subtitleFileLineLast" }));
    const buttons = screen.getAllByRole("button", { name: /subtitleFileExport/ });
    await user.click(buttons[buttons.length - 1]);
    await waitFor(() => expect(saved).toEqual([{ name: "访谈.vtt" }]));
    expect(urls[0]).toContain("/api/sequences/seq/subtitles/export?track_id=s1&format=vtt&line=last");
  });

  it("素材库收到的 .srt / .vtt 认得出是字幕文件", () => {
    expect(isSubtitleFile(new File([""], "台词.SRT"))).toBe(true);
    expect(isSubtitleFile(new File([""], "a.vtt"))).toBe(true);
    expect(isSubtitleFile(new File([""], "clip.mp4"))).toBe(false);
  });
});
