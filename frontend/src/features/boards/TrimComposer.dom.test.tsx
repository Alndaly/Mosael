/** @vitest-environment jsdom */
/**
 * 「剪一段」面板上的开关从媒体种类来。
 *
 * 音频也摆着「去掉声音」时,点了它剪出来的是一个空文件 —— 音频本身就是那段声音,任务必然报错。
 */
import React from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import type { BoardItem } from "@/api/client";
import { TrimComposer } from "./TrimComposer";

vi.mock("@/app/preferences", () => ({ useI18n: () => (key: string) => key }));
vi.mock("@xyflow/react", () => ({
  NodeToolbar: ({ children }: { children: React.ReactNode }) => children,
  Position: { Bottom: "bottom" },
}));
//: 素材库里查不到时长 —— 不画轨,退回填秒数,这里要看的只是那排开关。
vi.mock("@tanstack/react-query", () => ({ useQuery: () => ({ data: [] }) }));

const clip = (kind: "video" | "audio") =>
  ({ id: kind, kind, x: 0, y: 0, asset_id: `${kind}-asset` }) as BoardItem & { kind: "video" | "audio" };

it("音频没有「去掉声音」—— 它本身就是那段声音", () => {
  render(<TrimComposer item={clip("audio")} assetId="audio-asset" workspaceId="w" busy={false} onTrim={vi.fn()} onGrabFrame={vi.fn()} />);
  expect(screen.queryByTitle("boardKeepSound")).toBeNull();
  expect(screen.queryByTitle("boardGrabFrameTitle")).toBeNull();
});

it("视频有「去掉声音」,打开后发出去的是 mute", () => {
  const onTrim = vi.fn();
  render(<TrimComposer item={clip("video")} assetId="video-asset" workspaceId="w" busy={false} onTrim={onTrim} />);
  fireEvent.click(screen.getByTitle("boardKeepSound"));
  fireEvent.change(screen.getByLabelText("boardTrimEndLabel"), { target: { value: "3" } });
  fireEvent.click(screen.getByRole("button", { name: /boardTrimSubmit/ }));
  expect(onTrim).toHaveBeenCalledWith({ start: 0, end: 3, mute: true });
});
