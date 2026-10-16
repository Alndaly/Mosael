/** @vitest-environment jsdom */
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

vi.mock("@/app/preferences", () => ({ useI18n: () => (key: string) => key }));
vi.mock("@/api/client", () => ({ fetchWaveform: async () => ({ peaks: [0.1, .5, .8, .2] }) }));
import { MediaPreviewPlayer } from "./MediaPreviewPlayer";

describe("media preview transport", () => {
  it("seeks and adjusts volume without native media controls", () => {
    const { container } = render(<MediaPreviewPlayer src="/sample.mp4" kind="video" autoPlay={false} />);
    const video = container.querySelector("video")!;
    Object.defineProperty(video, "duration", { value: 120 });
    fireEvent.loadedMetadata(video);
    fireEvent.change(screen.getByRole("slider", { name: "mediaSeek" }), { target: { value: "35" } });
    expect(video.currentTime).toBe(35);
    fireEvent.change(screen.getByRole("slider", { name: "mediaVolume" }), { target: { value: ".4" } });
    expect(video.volume).toBe(.4);
    fireEvent.click(screen.getByRole("button", { name: "boardMute" }));
    expect(video.muted).toBe(true);
    expect(video.controls).toBe(false);
    fireEvent.play(video);
    expect(screen.getByRole("button", { name: "boardPause" })).toBeInTheDocument();
    fireEvent.ended(video);
    expect(screen.getByRole("button", { name: "boardPlay" })).toBeInTheDocument();
  });

  it("拖动时滑块跟手;松手后等跳转落地才交还给画面,不回弹", () => {
    //: 此前滑块的值只跟着画面(timeupdate)走:拖动中画面还没跳过去,滑块就被拽回原处,一顿一顿。
    const { container } = render(<MediaPreviewPlayer src="/sample.mp4" kind="video" autoPlay={false} />);
    const video = container.querySelector("video")!;
    Object.defineProperty(video, "duration", { value: 120 });
    let seeking = false;
    Object.defineProperty(video, "seeking", { get: () => seeking });
    fireEvent.loadedMetadata(video);
    const bar = screen.getByRole("slider", { name: "mediaSeek" }) as HTMLInputElement;

    seeking = true;
    fireEvent.change(bar, { target: { value: "40" } });
    fireEvent.change(bar, { target: { value: "60" } });
    expect(video.currentTime).toBe(60);
    expect(bar.value).toBe("60"); // 画面还停在 0,滑块在指针那儿

    fireEvent.pointerUp(bar);
    expect(bar.value).toBe("60"); // 跳转还没落地:不弹回 0

    seeking = false;
    fireEvent.timeUpdate(video);
    fireEvent.seeked(video);
    expect(bar.value).toBe("60"); // 落地后交还给画面,画面此时就在 60

    video.currentTime = 75;
    fireEvent.timeUpdate(video);
    expect(bar.value).toBe("75"); // 之后照常跟着画面走
  });

  //: 素材详情右栏点某一镜那一行时,跳转请求走这里(ADR 0061 §5)。同一个秒数连点两下也要跳第二次 ——
  //: 所以认的是**每一次请求**(对象换了一个),不是值变没变。
  it("外部说跳到第几秒,就跳到那一秒", () => {
    const { container, rerender } = render(<MediaPreviewPlayer src="/sample.mp4" kind="video" autoPlay={false} />);
    const video = container.querySelector("video")!;
    Object.defineProperty(video, "duration", { value: 120 });
    fireEvent.loadedMetadata(video);

    rerender(<MediaPreviewPlayer src="/sample.mp4" kind="video" autoPlay={false} seekTo={{ seconds: 12.4, seq: 1 }} />);
    expect(video.currentTime).toBe(12.4);

    rerender(<MediaPreviewPlayer src="/sample.mp4" kind="video" autoPlay={false} seekTo={{ seconds: 12.4, seq: 2 }} />);
    expect(video.currentTime).toBe(12.4);
  });

  //: 节奏条要知道「播到哪儿了」来高亮当前镜(ADR 0061 §5):报的就是进度条用的那一份时间,
  //: 不另开一路。回调每次换一个新身份也不该让时间重报(否则调用方一渲染就报一次)。
  it("播到哪儿就报到哪儿(素材详情右栏的节奏条用它高亮当前镜)", () => {
    const onTime = vi.fn();
    const { container, rerender } = render(<MediaPreviewPlayer src="/sample.mp4" kind="video" autoPlay={false} onTime={onTime} />);
    const video = container.querySelector("video")!;
    Object.defineProperty(video, "duration", { value: 120 });
    fireEvent.loadedMetadata(video);

    video.currentTime = 12.4;
    fireEvent.timeUpdate(video);
    expect(onTime).toHaveBeenLastCalledWith(12.4);

    const before = onTime.mock.calls.length;
    rerender(<MediaPreviewPlayer src="/sample.mp4" kind="video" autoPlay={false} onTime={vi.fn()} />);
    expect(onTime.mock.calls.length).toBe(before); // 只是换了个函数身份,不重报
  });

  it("reports rejected playback and keeps the controls available", async () => {
    vi.spyOn(HTMLMediaElement.prototype, "play").mockRejectedValueOnce(new Error("unsupported"));
    render(<MediaPreviewPlayer src="/broken.wav" kind="audio" autoPlay={false} />);
    fireEvent.click(screen.getByRole("button", { name: "boardPlay" }));
    expect(await screen.findByRole("status")).toHaveTextContent("mediaPlaybackError");
    expect(screen.getByRole("slider", { name: "mediaVolume" })).toBeEnabled();
    vi.restoreAllMocks();
  });

  it("uses real waveform samples for the audio display", async () => {
    const { container } = render(<MediaPreviewPlayer assetId="audio" src="/sample.wav" kind="audio" autoPlay={false} />);
    await waitFor(() => expect(container.querySelectorAll("svg[viewBox='0 0 16 64'] rect")).toHaveLength(4));
    expect(container.querySelector("video")).toBeNull();
  });
});
