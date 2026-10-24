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
vi.mock("@/app/preferences", () => ({ useI18n: () => (key: string) => key }));

import { DictateButton } from "@/features/agent/DictateButton";

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

//: 真的 Response:请求走的是 api/transport,报错怎么转成人话也在那条路上,一起测到。
const reply = (status: number, body: unknown) =>
  vi.fn().mockResolvedValue(new Response(JSON.stringify(body), { status })) as unknown as typeof fetch;

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
      reply(200, { text: "把这句话填进去" }),
    );
    await waitFor(() => expect(onText).toHaveBeenCalledWith("把这句话填进去"));
  });

  it("后端说明失败原因时原样转给用户", async () => {
    // 「缺的是运行环境」这种话是他唯一能据以行动的信息,换成"识别失败"等于把它扔了。
    await speak(
      reply(422, { detail: "缺的是运行环境,不是模型" }),
    );
    await waitFor(() => expect(toastError).toHaveBeenCalledWith("缺的是运行环境,不是模型"));
  });

  it("一个字都没识别出来也要说话", async () => {
    const { onText } = await speak(
      reply(200, { text: "   " }),
    );
    await waitFor(() => expect(toastError).toHaveBeenCalled());
    expect(onText).not.toHaveBeenCalled();
  });

  it("录完把音轨关掉 —— 否则系统的录音指示灯一直亮着", async () => {
    const { track } = await speak(
      reply(200, { text: "好" }),
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

  it("停下来等识别的时候,按钮说自己在转写 —— 而不是还写着「说话输入」", async () => {
    //: 录音停下到识别回来是一段没有声音的等待;那颗按钮只剩一圈转,名字还说着已经做完的事
    //: 的话,悬停得到的就是一句错的解释。
    vi.stubGlobal("fetch", vi.fn().mockReturnValue(new Promise<Response>(() => {})) as unknown as typeof fetch);
    grantMic();
    render(<DictateButton onText={vi.fn()} />);
    fireEvent.click(screen.getByRole("button", { name: "dictate" }));
    await waitFor(() => expect(FakeRecorder.last).not.toBeNull());

    FakeRecorder.last!.stop();

    await waitFor(() => expect(screen.getByRole("button", { name: "transcribing" })).toBeTruthy());
  });
});

it("录音时那一格会显示实时电平;没在录时不出现(jsdom 里没有 AudioContext 也不影响录音)", async () => {
  const onText = vi.fn();
  const track = grantMic();
  vi.stubGlobal("fetch", reply(200, { text: "补一句" }));
  render(<DictateButton onText={onText} />);

  //: 没在录:没有电平条 —— 空闲时多一格东西只会让人以为它在听。
  expect(document.querySelector("[data-dictate-level]")).toBeNull();

  fireEvent.click(screen.getByRole("button"));
  await waitFor(() => expect(FakeRecorder.last).not.toBeNull());

  //: 录音中:电平条在,而且带着 aria 值(读屏能念出来)。jsdom 没有 AudioContext,
  //: 所以这里同时也钉住了"拿不到分析节点时按钮照常工作"。
  const meter = await screen.findByRole("progressbar", { name: "dictateLevel" });
  expect(meter.getAttribute("aria-valuenow")).toBe("0");

  fireEvent.click(screen.getByRole("button"));
  await waitFor(() => expect(document.querySelector("[data-dictate-level]")).toBeNull());
  expect(track.stop).toHaveBeenCalled();
});
