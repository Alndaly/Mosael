/** @vitest-environment jsdom */
/**
 * 念出来的两条不变量,错了都**不会报错**:
 *
 * · **同时只响一个** —— 连点两条消息,两段语音叠在一起是听不清的,而每个按钮只知道自己;
 * · **没配音色不是失败** —— 那是个待办(去设置里选一个),报成红色的错等于让人以为坏了。
 */

import React from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const toastError = vi.fn();
const toastMessage = vi.fn();
vi.mock("sonner", () => ({
  toast: {
    error: (...args: unknown[]) => toastError(...args),
    message: (...args: unknown[]) => toastMessage(...args),
  },
}));
vi.mock("@/api/client", () => ({ API_BASE: "", getAuthToken: () => "tok" }));
vi.mock("@/app/preferences", () => ({ useI18n: () => (key: string) => key }));

import { SpeakButton } from "@/components/agent/SpeakButton";

const played: { pause: ReturnType<typeof vi.fn> }[] = [];

class FakeAudio {
  pause = vi.fn();
  play = vi.fn().mockResolvedValue(undefined);
  onended: (() => void) | null = null;
  onerror: (() => void) | null = null;
  constructor(public src: string) {
    played.push(this);
  }
}

function okAudio() {
  return vi.fn().mockResolvedValue({ ok: true, blob: async () => new Blob(["a"]) }) as unknown as typeof fetch;
}

beforeEach(() => {
  toastError.mockClear();
  toastMessage.mockClear();
  played.length = 0;
  vi.stubGlobal("Audio", FakeAudio as unknown as typeof Audio);
  vi.stubGlobal("URL", { createObjectURL: () => "blob:x", revokeObjectURL: vi.fn() });
});

describe("念给我听", () => {
  it("点一下就播", async () => {
    vi.stubGlobal("fetch", okAudio());
    render(<SpeakButton text="念这句" workspaceId="w1" />);
    fireEvent.click(screen.getByRole("button"));
    await waitFor(() => expect(played).toHaveLength(1));
    expect(played[0].pause).not.toHaveBeenCalled();
  });

  it("连点两条时,前一条要停下来", async () => {
    vi.stubGlobal("fetch", okAudio());
    render(
      <>
        <SpeakButton text="第一条" workspaceId="w1" />
        <SpeakButton text="第二条" workspaceId="w1" />
      </>,
    );
    const [first, second] = screen.getAllByRole("button");
    fireEvent.click(first);
    await waitFor(() => expect(played).toHaveLength(1));
    fireEvent.click(second);
    await waitFor(() => expect(played).toHaveLength(2));
    // 两段一起响是听不清的 —— 后点的接管。
    expect(played[0].pause).toHaveBeenCalled();
  });

  it("没配音色是待办,不是错误", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: false,
        status: 409,
        json: async () => ({ detail: "还没有选语音对话的音色" }),
      }) as unknown as typeof fetch,
    );
    render(<SpeakButton text="念" workspaceId="w1" />);
    fireEvent.click(screen.getByRole("button"));
    await waitFor(() => expect(toastMessage).toHaveBeenCalledWith("还没有选语音对话的音色"));
    expect(toastError).not.toHaveBeenCalled();
  });

  it("真失败时按原因报错", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: false,
        status: 422,
        json: async () => ({ detail: "这条连接没有配 API Key" }),
      }) as unknown as typeof fetch,
    );
    render(<SpeakButton text="念" workspaceId="w1" />);
    fireEvent.click(screen.getByRole("button"));
    await waitFor(() => expect(toastError).toHaveBeenCalledWith("这条连接没有配 API Key"));
  });

  it("没有内容就不给点 —— 空消息念不出东西", () => {
    vi.stubGlobal("fetch", okAudio());
    render(<SpeakButton text="   " workspaceId="w1" />);
    expect(screen.getByRole("button")).toBeDisabled();
  });
});
