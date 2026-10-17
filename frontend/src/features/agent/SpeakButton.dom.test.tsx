/** @vitest-environment jsdom */
/**
 * 念出来的两条不变量,错了都**不会报错**:
 *
 * · **同时只响一个** —— 连点两条消息,两段语音叠在一起是听不清的,而每个按钮只知道自己;
 * · **没配音色不是失败** —— 那是个待办(去设置里选一个),报成红色的错等于让人以为坏了。
 *
 * 请求走真的 transport(只替掉 fetch):语言头、报错正文怎么取,都是那一份实现说了算 ——
 * 此前这里手写 fetch,不带 Accept-Language,那句 409 永远是中文。
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
vi.mock("@/app/preferences", () => ({ useI18n: () => (key: string) => key }));

const speech = vi.hoisted(() => ({ mode: "early" as "early" | "whole" }));
vi.mock("@/features/agent/speechSettings", () => ({
  loadSpeechMode: async () => speech.mode,
  prefetchSpeechMode: () => {},
  rememberSpeechMode: () => {},
  speechModeOf: () => speech.mode,
}));

import { configureApiLocale } from "@/api/client";
import { SpeakButton } from "@/features/agent/SpeakButton";

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
  return vi.fn(async () => new Response(new Blob(["a"]), { status: 200 })) as unknown as typeof fetch;
}

function failing(status: number, detail: string) {
  return vi.fn(async () => new Response(JSON.stringify({ detail }), { status })) as unknown as typeof fetch;
}

beforeEach(() => {
  speech.mode = "early";
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
    vi.stubGlobal("fetch", failing(409, "还没有选语音对话的音色"));
    render(<SpeakButton text="念" workspaceId="w1" />);
    fireEvent.click(screen.getByRole("button"));
    await waitFor(() => expect(toastMessage).toHaveBeenCalledWith("还没有选语音对话的音色"));
    expect(toastError).not.toHaveBeenCalled();
  });

  it("真失败时按原因报错", async () => {
    vi.stubGlobal("fetch", failing(422, "这条连接没有配 API Key"));
    render(<SpeakButton text="念" workspaceId="w1" />);
    fireEvent.click(screen.getByRole("button"));
    await waitFor(() => expect(toastError).toHaveBeenCalledWith("这条连接没有配 API Key"));
  });

  it("按界面语言要那句话 —— 请求带着 Accept-Language", async () => {
    const fetchSpy = okAudio();
    vi.stubGlobal("fetch", fetchSpy);
    configureApiLocale({ locale: "en-US", unreachable: (url) => url });
    try {
      render(<SpeakButton text="read this" workspaceId="w1" />);
      fireEvent.click(screen.getByRole("button"));
      await waitFor(() => expect(played).toHaveLength(1));
    } finally {
      configureApiLocale({ locale: "zh-CN", unreachable: (url) => url });
    }
    const [url, init] = (fetchSpy as unknown as { mock: { calls: [string, RequestInit][] } }).mock.calls[0];
    expect(url).toMatch(/\/api\/agent\/speech$/);
    expect((init.headers as Record<string, string>)["Accept-Language"]).toBe("en-US");
    expect(JSON.parse(String(init.body))).toEqual({ text: "read this", workspace_id: "w1" });
  });

  it("播到一半再点一下就停:后面的句子不再合成、不再播,按钮回到可点", async () => {
    vi.stubGlobal("fetch", okAudio());
    render(<SpeakButton text="第一句长一点。第二句也长一点。第三句同样不短。" workspaceId="w1" />);
    const button = screen.getByRole("button");
    fireEvent.click(button);
    //: 第一句的音频已经交给播放器了(第二句的合成可能已经在途中)。
    await waitFor(() => expect(played).toHaveLength(1));
    await waitFor(() => expect(button).toHaveAttribute("aria-label", "speakStop"));
    fireEvent.click(button);
    await waitFor(() => expect(button).toHaveAttribute("aria-label", "speak"));
    //: 在途 / 后面的句子都不再播 —— 否则打断之后下一句还会自己响起来。
    expect(played).toHaveLength(1);
    expect(played[0].pause).toHaveBeenCalled();
  });

  it("等整段:整段一次合成,行为和加流水线之前一样", async () => {
    speech.mode = "whole";
    const fetchSpy = okAudio();
    vi.stubGlobal("fetch", fetchSpy);
    render(<SpeakButton text="第一句长一点。第二句也长一点。第三句同样不短。" workspaceId="w1" />);
    fireEvent.click(screen.getByRole("button"));
    await waitFor(() => expect(played).toHaveLength(1));
    const speechCalls = (fetchSpy as unknown as { mock: { calls: [string][] } }).mock.calls
      .map(([url]) => url)
      .filter((url) => url.endsWith("/api/agent/speech"));
    expect(speechCalls).toHaveLength(1);
    expect(JSON.parse(String((fetchSpy as unknown as { mock: { calls: [string, RequestInit][] } }).mock.calls.find(([url]) => url.endsWith("/api/agent/speech"))![1].body)).text)
      .toBe("第一句长一点。第二句也长一点。第三句同样不短。");
  });

  it("没有内容就不给点 —— 空消息念不出东西", () => {
    vi.stubGlobal("fetch", okAudio());
    render(<SpeakButton text="   " workspaceId="w1" />);
    expect(screen.getByRole("button")).toBeDisabled();
  });
});
