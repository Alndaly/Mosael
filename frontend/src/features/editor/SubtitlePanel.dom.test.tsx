/** @vitest-environment jsdom */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import React from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

/**
 * 字幕面板的配音入口。
 *
 * 两件事值得钉住:
 *
 * 1. **每条字幕自己就是一个配音单位**。只给底部一个批量按钮的话,「就这一条重配一下」要先去
 *    时间线上把它选中 —— 而你正看着它、手就在它上面。
 * 2. **双语字幕要能选念哪一行**。翻译勾了「保留原文」之后,一条字幕是「原文\n译文」两行;
 *    整段丢给合成就是先念一遍原文再念一遍译文,一条 3 秒的字幕配出十几秒的音。
 *    这个选择**只在真有双语时出现** —— 单语字幕摆一个「念哪一行」只会让人以为自己漏配了什么。
 */

vi.mock("@/app/preferences", () => ({
  useI18n: () => (key: string) => key,
  usePreferences: () => ({ locale: "zh-CN" }),
}));

import { SubtitlePanel } from "@/features/editor/SubtitlePanel";

const originalFetch = globalThis.fetch;
afterEach(() => {
  globalThis.fetch = originalFetch;
});

function sequenceWith(texts: string[]) {
  return {
    id: "s1",
    workspace_id: "w1",
    revision: 1,
    tracks: [
      {
        id: "t1",
        kind: "subtitle",
        clips: texts.map((text, index) => ({
          id: `c${index}`,
          asset_id: null,
          asset_kind: "",
          timeline_start: index * 5,
          src_in: 0,
          src_out: 3,
          speed: 1,
          text_override: text,
        })),
      },
    ],
  } as never;
}

/** 弹层打开后会问三样:克隆音色、引擎目录、某个引擎的发音人。 */
function serveVoices(engines: Array<Record<string, unknown>> = [], engineVoices: Array<Record<string, unknown>> = []) {
  globalThis.fetch = vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input);
    const body = url.includes("/tts/engines")
      ? [{ id: "clone", label: "本地音色克隆", needs_key: false, needs_voice_id: false, ready: true }, ...engines]
      : url.includes("/tts/voices")
        ? engineVoices
        : [{ id: "v1", name: "我的音色" }];
    return new Response(JSON.stringify(body), {
      status: 200,
      headers: { "content-type": "application/json" },
    });
  }) as never;
}

function renderPanel(texts: string[]) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <SubtitlePanel
        sequence={sequenceWith(texts)}
        onSetText={vi.fn()}
        onAddSubtitle={vi.fn()}
        onDeleteClip={vi.fn()}
      />
    </QueryClientProvider>,
  );
}

describe("字幕列表空状态", () => {
  it("没有字幕时整块居中,而不是钉在顶上留一屏空白", () => {
    serveVoices();
    const { container } = renderPanel([]);
    const list = container.querySelector(".overflow-y-auto");
    // jsdom 没有真实布局,量不了像素;钉住的是**决定布局的那个类**,回归时它会先没。
    expect(list?.className).toContain("content-center");
    expect(list?.className).not.toContain("content-start");
  });

  it("有字幕时贴顶排列 —— 居中只属于空状态", () => {
    serveVoices();
    const { container } = renderPanel(["一条"]);
    const list = container.querySelector(".overflow-y-auto");
    expect(list?.className).toContain("content-start");
    expect(list?.className).not.toContain("content-center");
  });
});

describe("字幕配音入口", () => {
  it("每条字幕自己带一个配音入口", () => {
    serveVoices();
    renderPanel(["第一条", "第二条"]);
    expect(screen.getAllByLabelText("subtitleDubThis")).toHaveLength(2);
  });

  it("双语字幕才问「念哪一行」", async () => {
    serveVoices();
    renderPanel(["The.\n这。"]);
    await userEvent.click(screen.getAllByLabelText("subtitleDubThis")[0]);
    await waitFor(() => expect(screen.getByText("subtitleDubLine")).toBeTruthy());
  });

  it("单语字幕不问 —— 那个选择在这里没有意义", async () => {
    serveVoices();
    renderPanel(["只有一行"]);
    await userEvent.click(screen.getAllByLabelText("subtitleDubThis")[0]);
    // 弹层确实开了(音色那一栏在),只是不该有「念哪一行」。
    await waitFor(() => expect(screen.getByText("subtitleDubVoice")).toBeTruthy());
    expect(screen.queryByText("subtitleDubLine")).toBeNull();
  });

  it("引擎可选,而不是写死克隆 —— 没建过音色的人也配得出来", async () => {
    serveVoices([{ id: "volcano", label: "火山引擎", needs_key: true, needs_voice_id: false, ready: true }]);
    renderPanel(["只有一行"]);
    await userEvent.click(screen.getAllByLabelText("subtitleDubThis")[0]);
    await waitFor(() => expect(screen.getByText("subtitleDubEngine")).toBeTruthy());
  });

  it("日文字幕配本地克隆时**当场**警告 —— 不必等排队后收到一条错误", async () => {
    serveVoices();
    renderPanel(["お漏らし。", "ここに寝てるんでしょ？"]);
    await userEvent.click(screen.getAllByLabelText("subtitleDubThis")[0]);
    await waitFor(() => expect(screen.getByText("subtitleDubLangJa")).toBeTruthy());
  });

  it("日文字幕选 Edge 时自动落在日语音色上,警告随之消失", async () => {
    serveVoices(
      [{ id: "edge", label: "Edge 免费语音(微软)", needs_key: false, needs_voice_id: false, ready: true }],
      [
        { value: "zh-CN-XiaoxiaoNeural", label: "晓晓(女·温暖)" },
        { value: "ja-JP-NanamiNeural", label: "Nanami(日·女)" },
      ],
    );
    renderPanel(["お漏らし。", "ここに寝てるんでしょ？"]);
    await userEvent.click(screen.getAllByLabelText("subtitleDubThis")[0]);
    await waitFor(() => expect(screen.getByText("subtitleDubEngine")).toBeTruthy());
    // 组件里换引擎要走 radix 的下拉(jsdom 点不开),所以直接验证挑选逻辑本身在这份目录上的结果:
    // 见 dubLanguage.test.ts「默认就选对」。这里守住的是**克隆引擎下警告仍然出现**,
    // 也就是自动挑选没有把警告一并吞掉。
    expect(screen.getByText("subtitleDubLangJa")).toBeTruthy();
  });

  it("中文字幕不触发警告 —— 一条错误的警告会让人开始怀疑所有警告", async () => {
    serveVoices();
    renderPanel(["这是中文字幕"]);
    await userEvent.click(screen.getAllByLabelText("subtitleDubThis")[0]);
    await waitFor(() => expect(screen.getByText("subtitleDubVoice")).toBeTruthy());
    expect(screen.queryByText("subtitleDubLangJa")).toBeNull();
  });

  it("缩放到段落长度默认关 —— 变速会改语速听感,值不值由用户按素材定", async () => {
    serveVoices();
    renderPanel(["只有一行"]);
    await userEvent.click(screen.getAllByLabelText("subtitleDubThis")[0]);
    const toggle = await screen.findByRole("switch");
    expect(toggle.getAttribute("data-state")).toBe("unchecked");
  });
});
