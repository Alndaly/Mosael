/** @vitest-environment jsdom */
/**
 * 说话输入的两条不变量,错了都**不会报错**:
 *
 * · 识别出来的文字是**追加**,不是覆盖 —— 覆盖会吃掉用户已经打的半句,而他不会想到是这里干的;
 * · 失败要**出声** —— 一个点了没反应的麦克风按钮,和"它在听但没听清"长得一模一样。
 */

import React from "react";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

// 工厂里**延迟引用**:vi.mock 会被提升到变量声明之前,直接把 fn 塞进去会撞
// "Cannot access before initialization"(仓库里 composerAttachments 那条是同一个写法)。
const toastError = vi.fn();
vi.mock("sonner", () => ({ toast: { error: (...args: unknown[]) => toastError(...args) } }));
vi.mock("@/api/client", () => ({ API_BASE: "", getAuthToken: () => "tok" }));
vi.mock("@/app/preferences", () => ({ useI18n: () => (key: string) => key }));

import { DictateButton } from "@/components/agent/DictateButton";

class FakeRecorder {
  static last: FakeRecorder | null = null;
  ondataavailable: ((event: { data: Blob }) => void) | null = null;
  onstop: (() => void) | null = null;
  mimeType = "audio/webm";
  constructor(public stream: MediaStream) {
    FakeRecorder.last = this;
  }
  start() {}
  stop() {
    this.ondataavailable?.({ data: new Blob(["audio"], { type: "audio/webm" }) });
    this.onstop?.();
  }
}

function grantMic() {
  const track = { stop: vi.fn() };
  Object.defineProperty(navigator, "mediaDevices", {
    configurable: true,
    value: { getUserMedia: vi.fn().mockResolvedValue({ getTracks: () => [track] } as unknown as MediaStream) },
  });
  return track;
}

beforeEach(() => {
  toastError.mockClear();
  FakeRecorder.last = null;
  vi.stubGlobal("MediaRecorder", FakeRecorder as unknown as typeof MediaRecorder);
});

async function speak(fetchImpl: typeof fetch, onText = vi.fn()) {
  vi.stubGlobal("fetch", fetchImpl);
  const track = grantMic();
  render(<DictateButton onText={onText} />);
  fireEvent.click(screen.getByRole("button"));
  await waitFor(() => expect(FakeRecorder.last).not.toBeNull());
  FakeRecorder.last!.stop();
  return { onText, track };
}

describe("说话输入", () => {
  it("把识别到的文字交给调用方", async () => {
    const { onText } = await speak(
      vi.fn().mockResolvedValue({ ok: true, json: async () => ({ text: "把这句话填进去" }) }) as unknown as typeof fetch,
    );
    await waitFor(() => expect(onText).toHaveBeenCalledWith("把这句话填进去"));
  });

  it("后端说明失败原因时原样转给用户", async () => {
    // 「缺的是运行环境」这种话是他唯一能据以行动的信息,换成"识别失败"等于把它扔了。
    await speak(
      vi.fn().mockResolvedValue({
        ok: false,
        json: async () => ({ detail: "缺的是运行环境,不是模型" }),
      }) as unknown as typeof fetch,
    );
    await waitFor(() => expect(toastError).toHaveBeenCalledWith("缺的是运行环境,不是模型"));
  });

  it("一个字都没识别出来也要说话", async () => {
    const { onText } = await speak(
      vi.fn().mockResolvedValue({ ok: true, json: async () => ({ text: "   " }) }) as unknown as typeof fetch,
    );
    await waitFor(() => expect(toastError).toHaveBeenCalled());
    expect(onText).not.toHaveBeenCalled();
  });

  it("录完把音轨关掉 —— 否则系统的录音指示灯一直亮着", async () => {
    const { track } = await speak(
      vi.fn().mockResolvedValue({ ok: true, json: async () => ({ text: "好" }) }) as unknown as typeof fetch,
    );
    await waitFor(() => expect(track.stop).toHaveBeenCalled());
  });

  it("拿不到麦克风时说人话,而不是静静地什么都不做", async () => {
    Object.defineProperty(navigator, "mediaDevices", {
      configurable: true,
      value: { getUserMedia: vi.fn().mockRejectedValue(new Error("denied")) },
    });
    render(<DictateButton onText={vi.fn()} />);
    fireEvent.click(screen.getByRole("button"));
    await waitFor(() => expect(toastError).toHaveBeenCalled());
  });
});
