/** @vitest-environment jsdom */
import React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";

import type { GenerationOption } from "@/api/client";

/**
 * 数字人的两条描述符规则在生成页上(ADR 0028 §2):时长跟着驱动音频走的模型写明它跟着谁;
 * 会截掉音频后半段的模型(万相 2.7),所选时长短于挂着的音频时提醒截掉几秒,一键改成按音频长度。
 */

vi.mock("@/api/client", () => ({
  listAssets: vi.fn(async () => [{ id: "voice-12s", kind: "audio", name: "旁白", media_info: { duration: 12.4 } }]),
}));
vi.mock("@/app/preferences", () => ({
  useI18n: () => (key: string) =>
    ({
      genParam_driving_audio: "驱动音频",
      genDurationFollows: "跟着{role}的长度",
      genDurationTruncates: "{role}有 {source} 秒,后 {cut} 秒会被截掉",
      genDurationUseSource: "改成 {seconds} 秒",
    })[key] ?? key,
}));

import { DurationFollowsNote, TruncationHint, durationFollowsRole } from "./durationFollows";

afterEach(cleanup);

const wan27 = { capabilities: { truncates_role: "driving_audio", min_duration_seconds: 2, max_duration_seconds: 15 } } as unknown as GenerationOption;
const s2v = { capabilities: { duration_follows: "driving_audio" } } as unknown as GenerationOption;

function mount(ui: React.ReactElement) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>);
}

it("时长跟着驱动音频的模型:时长那一栏写明跟着谁", () => {
  expect(durationFollowsRole(s2v)).toBe("driving_audio");
  expect(durationFollowsRole(wan27)).toBe("");
  mount(<DurationFollowsNote role="driving_audio" />);
  expect(screen.getByText("跟着驱动音频的长度")).toBeTruthy();
});

it("音频 12.4 秒、选了 5 秒:说后 7.4 秒会被截掉,一键改成 13 秒", async () => {
  const onUse = vi.fn();
  mount(
    <TruncationHint
      model={wan27}
      workspaceId="ws"
      frames={{ driving_audio: [{ url: "", assetId: "voice-12s", assetName: "旁白" }] }}
      durationSeconds="5"
      bounds={{ min: 2, max: 15 }}
      onUseSourceLength={onUse}
    />,
  );
  expect(await screen.findByText("驱动音频有 12.4 秒,后 7.4 秒会被截掉")).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "改成 13 秒" }));
  expect(onUse).toHaveBeenCalledWith(13);
});

it("所选时长够长、没挂音频、模型不截的,都不提醒", async () => {
  const { listAssets } = await import("@/api/client");
  const frames = { driving_audio: [{ url: "", assetId: "voice-12s", assetName: "旁白" }] };
  const common = { workspaceId: "ws", bounds: { min: 2, max: 15 }, onUseSourceLength: vi.fn() };
  vi.mocked(listAssets).mockClear();
  mount(<TruncationHint {...common} model={wan27} frames={frames} durationSeconds="15" />);
  mount(<TruncationHint {...common} model={wan27} frames={{}} durationSeconds="5" />);
  mount(<TruncationHint {...common} model={s2v} frames={frames} durationSeconds="5" />);
  //: 等素材清单到了再断言 —— 清单没到时本来就不提醒,立刻断言等于在空处断言。
  await waitFor(() => expect(listAssets).toHaveBeenCalled());
  await new Promise((resolve) => setTimeout(resolve, 20));
  expect(document.querySelector("[data-truncation-hint]")).toBeNull();
});
