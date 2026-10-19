/** @vitest-environment jsdom */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import React from "react";
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

/**
 * 点了那支笔要**真的打开**编辑表单。
 *
 * 用户报「点笔按钮没有任何用」。原因是我插入表单的那次字符串替换没匹配上锚点,而我**没加
 * 断言** —— 它静默地什么都没做。typecheck 照样过:`editing` 状态确实被按钮用着,只是没有
 * 任何东西读它。
 *
 * 这类"改了但没生效"靠类型检查抓不到,只有**按一下看看**能抓到。
 */

vi.mock("@/app/preferences", () => {
  //: 带占位符的那几条用真模板:其余键仍返回键名(老测试就是按键名断言的),但下载行里的
  //: 百分比 / 字节 / 速度必须能读出来,否则「进度真的在动」这件事没法验。
  const templates: Record<string, string> = {
    subtitleDubModelDownloadingSize: "下载中 {n}% · {done} / {total}",
    subtitleDubModelDownloadingUnknown: "下载中 · 已下载 {done} · 大小未知",
    subtitleDubModelFailed: "下载失败",
    subtitleDubModelFailedNoReason: "下载没有完成,也没有留下原因 —— 请重试。",
    subtitleDubModelStatusUnknown: "查不到模型下载状态",
    subtitleDubModelStatusUnknownHint: "网络或后端暂时连不上。再试一次;正在下载的任务不会因此停下。",
    subtitleDubModelLastAt: "最后一次 {time}",
    subtitleDubModelSizeUnknown: "大小未知",
    retry: "重试",
  };
  return {
    useI18n: () => (key: string) => templates[key] ?? key,
    usePreferences: () => ({ locale: "zh-CN" }),
  };
});
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn(), info: vi.fn() } }));

import { toast } from "sonner";
import { VoicePanel } from "@/features/editor/VoicePanel";
import { useEditorStore } from "@/features/editor/editorStore";

const voices = [{ id: "v1", name: "我的", reference_text: "", source: "upload", created_at: "2026-01-01T00:00:00Z", has_reference: true }];

// jsdom 没有 Pointer Capture,而 Radix 的 Select 在 pointerdown 里就要用它 —— 不补上,
// 展开下拉这件事在测试里根本做不到(它会抛 `hasPointerCapture is not a function`)。
beforeAll(() => {
  Object.assign(Element.prototype, {
    hasPointerCapture: () => false,
    setPointerCapture: () => {},
    releasePointerCapture: () => {},
    scrollIntoView: () => {},
  });
});

const originalFetch = globalThis.fetch;
afterEach(() => { globalThis.fetch = originalFetch; });
beforeEach(() => useEditorStore.getState().selectClip(null));

const localEngines = [
  { id: "f5-tts", label: "F5-TTS", status: "installed", runtime_ready: true, runtime_checked: true, supports_speed: true },
  { id: "fish-speech", label: "Fish Speech S2 Pro", status: "installed", runtime_ready: true, runtime_checked: true, supports_speed: false },
];

//: 默认只装了中英基础模型 —— 这台机器上最常见的样子,也是「日文念不了」的那个前提。
const BASE_WEIGHTS = [
  { id: "base", label: "基础模型", languages: ["zh", "en"], installed: true, status: "installed", expected_bytes: 1e9, progress: 1, message: "", note: "" },
  { id: "ja", label: "日语模型", languages: ["ja"], installed: false, status: "missing", expected_bytes: 1.4e9, progress: 0, message: "", note: "" },
];

function sequenceWith(texts: string[]) {
  return {
    id: "s1",
    workspace_id: "w1",
    revision: 1,
    tracks: [
      {
        id: "t1",
        kind: "subtitle",
        name: "S1",
        position: 0,
        clips: texts.map((text, index) => ({
          id: `c${index}`, track_id: "t1", asset_id: null, asset_kind: "", timeline_start: index * 5, src_in: 0, src_out: 3, speed: 1, text_override: text,
        })),
      },
    ],
  } as never;
}

type Served = {
  voices?: unknown[]; texts?: string[]; weights?: unknown[]; onOpenSubtitles?: () => void; admin?: boolean;
  sequence?: unknown; focusClipId?: string;
  /** 让 `/tts/f5-models` 返回错误:下载状态本身查不到时界面该说什么。 */
  f5Failure?: { code: number };
};

function renderPanel({
  voices: voiceData = voices, texts = ["一条字幕"], weights = BASE_WEIGHTS, onOpenSubtitles, admin = true, sequence, focusClipId,
  f5Failure,
}: Served = {}) {
  const dubRequests: Array<Record<string, unknown>> = [];
  const downloadCalls: string[] = [];
  globalThis.fetch = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    if (url.includes("/dub-subtitles")) {
      dubRequests.push(JSON.parse(String(init?.body)));
      return new Response(JSON.stringify({ id: "job-1", status: "queued" }), { status: 200, headers: { "content-type": "application/json" } });
    }
    //: 下载状态查不到(后端暂时连不上 / 500):比"假装它没在下载"更该说清楚的那一种。
    if (url.includes("/tts/f5-models") && f5Failure && f5Failure.code >= 400) {
      return new Response(JSON.stringify({ detail: "f5 status unavailable" }), {
        status: f5Failure.code, headers: { "content-type": "application/json" },
      });
    }
    if (url.includes("/tts/f5-models/") && url.endsWith("/download")) {
      downloadCalls.push(url);
      return new Response(JSON.stringify((weights as Record<string, unknown>[])[1]), {
        status: 200, headers: { "content-type": "application/json" },
      });
    }
    const body = url.includes("/api/auth/me")
      ? { is_deployment_admin: admin }
      : url.includes("/tts/f5-models")
      ? weights
      : url.includes("/api/tts/models")
        ? localEngines
        : url.includes("/api/settings/tts")
          ? { engine: "f5-tts", python_path: "", source: "modelscope" }
          : url.includes("/tts/engines")
            ? [
                { id: "builtin:clone", label: "本地音色克隆", needs_key: false, needs_voice_id: false, voices: [], note: "clone note", ready: true },
                { id: "builtin:edge", label: "Edge TTS", needs_key: false, needs_voice_id: false, voices: [], ready: true },
                { id: "builtin:volcano-podcast", label: "火山播客", needs_key: true, needs_voice_id: false, voices: [], ready: true },
              ]
            : url.includes("/tts/voices")
              ? [{ value: "edge-voice", label: "Edge Voice" }]
              : url.includes("/api/voices")
                ? voiceData
                : url.includes("/api/jobs/")
                  ? { id: "job-1", status: "running" }
                  : url.includes("/api/assets?")
                    ? { items: [], next_cursor: null, total: 0 }
                    : [];
    return new Response(JSON.stringify(body), { status: 200, headers: { "content-type": "application/json" } });
  }) as never;
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const view = render(
    <QueryClientProvider client={client}>
      <VoicePanel
        workspace={{ id: "w1", name: "W" } as never}
        project={{ id: "p1" } as never}
        sequence={(sequence ?? sequenceWith(texts)) as never}
        onOpenSubtitles={onOpenSubtitles}
        dubFocusClipId={focusClipId}
      />
    </QueryClientProvider>,
  );
  return { ...view, dubRequests, downloadCalls, client };
}

describe("音色库", () => {
  it("空音色使用禁用控件和紧凑空状态,不在生成按钮下堆提示", async () => {
    renderPanel({ voices: [] });

    expect(await screen.findByPlaceholderText("voiceLibraryPickEmpty")).toBeDisabled();
    const emptyTitle = await screen.findByText("voiceLibraryEmpty");
    const emptyState = emptyTitle.closest(".empty-state");
    expect(emptyState).not.toBeNull();
    expect(emptyState!.className).toContain("max-w-none!");
    expect(emptyState!.className).not.toMatch(/border-dashed|bg-background/);
    expect(screen.getByText("voiceEmpty")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "voiceFromSpeaker" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "voiceUpload" })).toBeInTheDocument();
    expect(screen.queryByText("clone note")).not.toBeInTheDocument();
  });

  it("从说话人使用弹窗,不再挤开音色列表", async () => {
    const user = userEvent.setup();
    renderPanel();

    await user.click(await screen.findByRole("button", { name: "voiceFromSpeaker" }));

    expect(screen.getByRole("dialog", { name: "voiceFromSpeaker" })).toBeInTheDocument();
  });

  it("上传克隆使用带录音入口的弹窗", async () => {
    const user = userEvent.setup();
    renderPanel();

    await user.click(await screen.findByRole("button", { name: "voiceUpload" }));

    const dialog = screen.getByRole("dialog", { name: "voiceUpload" });
    expect(dialog).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "voiceRecord" })).toBeInTheDocument();
    expect(dialog.querySelector('[data-slot="modal-footer"]')).not.toBeNull();
  });

  it("切换到远程语音引擎后隐藏本地音色库", async () => {
    const user = userEvent.setup();
    renderPanel();

    expect(await screen.findByText("voiceLibrary")).toBeInTheDocument();
    await user.click(screen.getByRole("combobox", { name: "voiceEngine" }));
    await user.click(await screen.findByRole("option", { name: "Edge TTS" }));

    await waitFor(() => expect(screen.queryByText("voiceLibrary")).not.toBeInTheDocument());
    expect(screen.queryByRole("button", { name: "voiceFromSpeaker" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "voiceUpload" })).not.toBeInTheDocument();
  });

  it("点铅笔打开编辑表单 —— 用户报的正是「点了没反应」", async () => {
    const user = userEvent.setup();
    renderPanel();
    const pencil = await screen.findByRole("button", { name: "voiceEdit" });

    await user.click(pencil);

    await waitFor(() => expect(screen.getByText("voiceEditHint")).toBeInTheDocument());
  });

  it("表单里能看到「自动识别」和「保存」", async () => {
    const user = userEvent.setup();
    renderPanel();

    await user.click(await screen.findByRole("button", { name: "voiceEdit" }));

    expect(screen.getByRole("button", { name: "voiceRecognize" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /save/ })).toBeInTheDocument();
  });

  it("没填参考文本的音色要标出来 —— 它在下拉里看起来和别的一样正常", async () => {
    renderPanel();

    expect(await screen.findByText("voiceNoReferenceText")).toBeInTheDocument();
  });

  // 剪辑页和设置页共用一份音色行(VoiceList):下面几条此前只有设置页有。
  it("删音色先确认,确认了才发请求;删失败要说出来", async () => {
    const user = userEvent.setup();
    renderPanel();
    const served = globalThis.fetch;
    const deletes: string[] = [];
    globalThis.fetch = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      if (init?.method === "DELETE") {
        deletes.push(String(input));
        return new Response(JSON.stringify({ detail: "voice in use" }), { status: 409, headers: { "content-type": "application/json" } });
      }
      return served(input, init);
    }) as never;

    await user.click(await screen.findByRole("button", { name: "delete" }));
    const dialog = await screen.findByRole("alertdialog", { name: "voiceDeleteTitle" });
    expect(deletes).toEqual([]);

    await user.click(within(dialog).getByRole("button", { name: "confirm" }));
    await waitFor(() => expect(deletes).toHaveLength(1));
    expect(deletes[0]).toContain("/api/voices/v1");
    await waitFor(() => expect(toast.error).toHaveBeenCalled());
  });

  it("没有参考音频的音色:试听键灰掉,而不是点了没声音", async () => {
    renderPanel({ voices: [{ ...voices[0], has_reference: false }] });
    expect(await screen.findByRole("button", { name: "voicePlay" })).toBeDisabled();
  });

  it("没声明授权的音色一行里写明;编辑表单里能补上声明", async () => {
    const user = userEvent.setup();
    renderPanel({ voices: [{ ...voices[0], consent_kind: "undeclared", consent_at: null }] });

    expect(await screen.findByText("voiceConsentMissing")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "voiceEdit" }));
    expect(await screen.findByRole("radiogroup", { name: "voiceConsentTitle" })).toBeInTheDocument();
  });
});

/**
 * 配音面板是**可拖宽的侧栏**,默认只有 250px 上下。把「克隆引擎 / 音色 / 语速」写成
 * `grid-cols-[1fr_1fr_88px]` 之后,引擎那一格实测只剩 65px —— 触发器显示成「F5-…」,
 * 展开的菜单被 SelectContent 的 `max-w-[trigger-width]` 一起压成 60px,两个选项变成
 * 「F5…」「Fi…」。**一个读不出选项的选择器等于没有这个功能**,而它正是这一轮加的。
 *
 * 根因不是"列宽给少了",是**用固定列数去排一个宽度会变的容器**:换成 3 列同样会在别的
 * 宽度上错。所以这里的判据是"这一行按内容需要换行",而不是"这一行是几列"。
 */
describe("配音面板的控件行(响应式)", () => {
  it("克隆的那一行会换行,而不是写死列数把每格挤成 65px", async () => {
    renderPanel();
    const picker = await screen.findByRole("combobox", { name: "voicePanelCloneEngine" });

    const row = picker.closest("div.flex-wrap");

    expect(row, "克隆引擎所在的行不会换行 —— 面板一窄就把三个控件挤成看不清的宽度").not.toBeNull();
    expect(row!.className, "行里还留着写死的列轨道").not.toMatch(/grid-cols-\[/);
  });

  it("引擎名有下限宽度 —— 它是这一行里最长的一个,不能被平均分配", async () => {
    renderPanel();
    const picker = await screen.findByRole("combobox", { name: "voicePanelCloneEngine" });

    const field = picker.closest("div.flex-wrap")!.querySelector<HTMLElement>(":scope > div");

    expect(field!.className).toMatch(/min-w-\[/);
  });

  it("两个引擎都在下拉里,没装好的标出来", async () => {
    const user = userEvent.setup();
    renderPanel();

    await user.click(await screen.findByRole("combobox", { name: "voicePanelCloneEngine" }));

    expect(await screen.findByRole("option", { name: "Fish Speech S2 Pro" })).toBeInTheDocument();
  });
});

/**
 * 给字幕配音 —— 原先是字幕页里的一个弹层,现在就是这一页的主表单。
 *
 * 1. **双语字幕要能选念哪一行**:翻译勾了「保留原文」之后,一条字幕是「原文\n译文」;整段丢给合成
 *    就是先念一遍原文再念一遍译文。这个选择**只在真有双语时出现**。
 * 2. **范围跟着时间线上的选中走** —— 字幕页每行的入口就是"选中它、切过来"。
 * 3. 语言对不上当场说,并把缺的那份权重的下载放在手边。
 */
describe("给字幕配音", () => {
  it("双语字幕才问「念哪一行」", async () => {
    renderPanel({ texts: ["The.\n这。"] });
    expect(await screen.findByRole("combobox", { name: "subtitleDubLine" })).toBeInTheDocument();
  });

  it("单语字幕不问 —— 那个选择在这里没有意义", async () => {
    renderPanel({ texts: ["只有一行"] });
    await screen.findByRole("button", { name: /subtitleDubApply/ });
    expect(screen.queryByRole("combobox", { name: "subtitleDubLine" })).toBeNull();
  });

  it("播客引擎不在可选引擎里 —— 它一次产出整段对话,在「AI 生成 → 音频」", async () => {
    const user = userEvent.setup();
    renderPanel();
    await user.click(await screen.findByRole("combobox", { name: "voiceEngine" }));
    expect(await screen.findByRole("option", { name: "Edge TTS" })).toBeInTheDocument();
    expect(screen.queryByRole("option", { name: "火山播客" })).toBeNull();
  });

  it("时间线上选中了几条,就只配那几条", async () => {
    useEditorStore.getState().selectClip("c1");
    const user = userEvent.setup();
    const { dubRequests } = renderPanel({ texts: ["第一条", "第二条"] });
    expect(await screen.findByText("subtitleTranslateSelectedOnly")).toBeInTheDocument();
    const apply = await screen.findByRole("button", { name: /subtitleDubApply/ });
    await waitFor(() => expect(apply).toBeEnabled());
    await user.click(apply);
    await waitFor(() => expect(dubRequests).toHaveLength(1));
    expect(dubRequests[0]).toMatchObject({ clip_ids: ["c1"], engine: "builtin:clone", voice_id: "v1", clone_engine: "f5-tts", speed: 1 });
  });

  it("两条字幕轨(双语分轨):一次只配一条,默认最下面那条,请求里带上轨道", async () => {
    const cue = (id: string, track: string, text: string) => ({
      id, track_id: track, asset_id: null, asset_kind: "", timeline_start: 0, src_in: 0, src_out: 3, speed: 1, text_override: text,
    });
    const sequence = {
      id: "s1", workspace_id: "w1", revision: 1,
      tracks: [
        { id: "zh", kind: "subtitle", name: "S2", position: 3, clips: [cue("z1", "zh", "你好")] },
        { id: "en", kind: "subtitle", name: "S1", position: 2, clips: [cue("e1", "en", "Hello")] },
      ],
    };
    const user = userEvent.setup();
    const { dubRequests } = renderPanel({ sequence });
    expect(await screen.findByRole("combobox", { name: "subtitleDubTrack" })).toBeInTheDocument();
    const apply = await screen.findByRole("button", { name: /subtitleDubApply/ });
    await waitFor(() => expect(apply).toBeEnabled());
    await user.click(apply);
    await waitFor(() => expect(dubRequests).toHaveLength(1));
    expect(dubRequests[0]).toMatchObject({ clip_ids: ["e1"], track_id: "en" });
  });

  it("字幕列表里点了某一条:只配那一条,不看时间线上的选中", async () => {
    useEditorStore.getState().selectClip("c0");
    const user = userEvent.setup();
    const { dubRequests } = renderPanel({ texts: ["第一条", "第二条"], focusClipId: "c1" });
    expect(await screen.findByText("subtitleDubFocused")).toBeInTheDocument();
    const apply = await screen.findByRole("button", { name: /subtitleDubApply/ });
    await waitFor(() => expect(apply).toBeEnabled());
    await user.click(apply);
    await waitFor(() => expect(dubRequests).toHaveLength(1));
    expect(dubRequests[0]).toMatchObject({ clip_ids: ["c1"], track_id: "t1" });
  });

  it("日文字幕 + 本地克隆:当场说缺哪份权重,并把下载放在手边", async () => {
    renderPanel({ texts: ["お漏らし。", "ここに寝てるんでしょ？"] });
    expect(await screen.findByText(/subtitleDubModelMissing/)).toBeInTheDocument();
    expect(await screen.findByRole("button", { name: "subtitleDubModelDownload" })).toBeInTheDocument();
  });

  it("看的人不是部署管理员:说缺哪份权重、由谁来下,不给一个一点就被拒的下载按钮", async () => {
    renderPanel({ texts: ["お漏らし。", "ここに寝てるんでしょ？"], admin: false });
    expect(await screen.findByText(/subtitleDubModelMissing/)).toBeInTheDocument();
    expect(screen.getByText("engineInstalledByAdmin")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "subtitleDubModelDownload" })).toBeNull();
  });

  it("日语权重装上之后,提示和下载入口一起消失", async () => {
    const weights = BASE_WEIGHTS.map((model) => ({ ...model, installed: true, status: "installed" }));
    renderPanel({ texts: ["お漏らし。", "ここに寝てるんでしょ？"], weights });
    // 两份权重都装了,「用哪份」的下拉出现 —— 说明权重清单已经到了,判断是基于它做的。
    expect(await screen.findByRole("combobox", { name: "subtitleDubWeights" })).toBeInTheDocument();
    expect(screen.queryByText(/subtitleDubModelMissing|subtitleDubLang/)).toBeNull();
  });

  it("Fish Speech 不拿 F5 的权重清单判语言 —— 它一份模型念多语", async () => {
    const user = userEvent.setup();
    renderPanel({ texts: ["お漏らし。", "ここに寝てるんでしょ？"] });
    await screen.findByText(/subtitleDubModelMissing/);
    await user.click(screen.getByRole("combobox", { name: "voicePanelCloneEngine" }));
    await user.click(await screen.findByRole("option", { name: "Fish Speech S2 Pro" }));
    await waitFor(() => expect(screen.queryByText(/subtitleDubModelMissing|subtitleDubLang/)).toBeNull());
  });

  it("中文字幕不触发警告 —— 一条错误的警告会让人开始怀疑所有警告", async () => {
    renderPanel({ texts: ["这是中文字幕"] });
    await screen.findByRole("button", { name: /subtitleDubApply/ });
    await waitFor(() => expect(screen.queryByText(/subtitleDubModelMissing|subtitleDubLang/)).toBeNull());
  });

  it("缩放到段落长度默认开 —— 和智能体、工作流同一个默认(变速夹在 0.9–1.5 倍)", async () => {
    renderPanel();
    const toggle = await screen.findByRole("switch");
    expect(toggle.getAttribute("data-state")).toBe("checked");
  });

  it("时间线上没有字幕:说清楚,并给一个去字幕页的按钮", async () => {
    const onOpenSubtitles = vi.fn();
    const user = userEvent.setup();
    renderPanel({ texts: [], onOpenSubtitles });
    await user.click(await screen.findByRole("button", { name: /subtitleDubOpenSubtitles/ }));
    expect(onOpenSubtitles).toHaveBeenCalledOnce();
    expect(screen.queryByRole("button", { name: /subtitleDubApply/ })).toBeNull();
  });
});

/**
 * 权重下载那一行:**状态从后端派生**,不是组件里的一次性动画。
 *
 * 维护者截图:点「下载这个模型」→「下载中 0% · 0 MB / 5.4 GB」一直不动 → 过一会儿 loading
 * 消失、又变回「下载这个模型」。两件事都在这里钉住:
 *
 * 1. 百分比从**字节**算,不从后端那个可能还停在 0 的 `progress` 算(截图里的 0% 就是这么来的);
 * 2. 任何终止都落到一个说得清的状态上:失败说原因 + 重试,查不到状态说查不到 —— 绝不悄无声息
 *    地回到初始按钮。
 */
describe("权重下载那一行", () => {
  const JA_MISSING = {
    id: "ja",
    label: "日语模型",
    languages: ["ja"],
    installed: false,
    status: "missing",
    expected_bytes: 5_400_000_000,
    total_is_estimate: false,
    progress: 0,
    downloaded_bytes: 0,
    total_bytes: null,
    speed_bps: 0,
    eta_seconds: null,
    message: "",
    error: "",
    failed_at: "",
  };

  /** 只装中英基础模型 + 一份日语权重;要测的那一档由 overrides 给。 */
  function weightsWithJa(overrides: Record<string, unknown>) {
    return [{ ...BASE_WEIGHTS[0] }, { ...JA_MISSING, ...overrides }];
  }

  it("刷新 / 重开面板后状态还在:后端说正在下,就直接显示「下载中 + 进度」", async () => {
    renderPanel({
      texts: ["お漏らし。"],
      // 后端的 progress 还停在 0(截图里的那一眼),但字节已经动了 —— 百分比该按字节走。
      weights: weightsWithJa({
        status: "downloading",
        downloaded_bytes: 1_200_000_000,
        total_bytes: 5_400_000_000,
        progress: 0,
        speed_bps: 1_500_000,
      }),
    });

    const bar = await screen.findByRole("progressbar", { name: "subtitleDubModelDownloadingLabel" });
    expect(bar).toHaveAttribute("aria-valuenow", "22");
    expect(await screen.findByText("下载中 22% · 1.2 GB / 5.4 GB")).toBeInTheDocument();
    expect(screen.getByText("1.5 MB/s")).toBeInTheDocument();
    // 正在下就不该还有一个「下载这个模型」在下面等着被再点一次。
    expect(screen.queryByRole("button", { name: "subtitleDubModelDownload" })).toBeNull();
  });

  it("下载失败:说原因 + 重试;不把 loading 悄悄换成按钮", async () => {
    const user = userEvent.setup();
    const { downloadCalls } = renderPanel({
      texts: ["お漏らし。"],
      weights: weightsWithJa({
        status: "failed",
        message: "连不上模型下载源(https://hf-mirror.com):check your connection",
        error: "LocalEntryNotFoundError: check your connection",
        failed_at: "2026-10-19T12:33:00Z",
      }),
    });

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("下载失败");
    expect(alert).toHaveTextContent("连不上模型下载源");
    expect(alert).toHaveTextContent(/最后一次/);

    //: 后端把 `error` 里的原文备好了(`message` 是人话);卡片主句只说人话,原文在点开的「详情」里。
    //: 此前 `detail` 没接上,这一栏有数据却看不见 —— 用户只能看到被截断的那一句。
    const summary = alert.querySelector("[data-failure-summary]")!;
    expect(summary.textContent, "主句是人话").toContain("连不上模型下载源");
    expect(summary.textContent, "原文不该挤进主句").not.toContain("LocalEntryNotFoundError");
    fireEvent.click(alert.querySelector<HTMLElement>("[data-failure-more]")!);
    const detail = (await screen.findByText("LocalEntryNotFoundError: check your connection")).closest("[data-failure-detail]");
    expect(detail, "原文在「详情」里").not.toBeNull();
    expect(detail!.textContent).toContain("LocalEntryNotFoundError");

    await user.click(screen.getByRole("button", { name: "重试" }));
    await waitFor(() => expect(downloadCalls).toHaveLength(1));
    expect(downloadCalls[0]).toContain("/tts/f5-models/ja/download");
    expect(screen.queryByRole("button", { name: "subtitleDubModelDownload" })).toBeNull();
  });

  it("进度会动:两次轮询的字节不同,百分比和字节跟着变", async () => {
    const weights = weightsWithJa({
      status: "downloading",
      downloaded_bytes: 1_000_000_000,
      total_bytes: 5_400_000_000,
      progress: 0,
    });
    const { client } = renderPanel({ texts: ["お漏らし。"], weights });

    expect(await screen.findByRole("progressbar", { name: "subtitleDubModelDownloadingLabel" }))
      .toHaveAttribute("aria-valuenow", "19");

    // 第二轮:后端多报了 1 GB。**刷新来的状态必须当回事** —— 这一行不是一次性的。
    const second = weights[1] as Record<string, unknown>;
    second.downloaded_bytes = 2_000_000_000;
    await act(async () => { await client.refetchQueries({ queryKey: ["f5-models"] }); });

    expect(await screen.findByRole("progressbar", { name: "subtitleDubModelDownloadingLabel" }))
      .toHaveAttribute("aria-valuenow", "37");
    expect(screen.getByText("下载中 37% · 2.0 GB / 5.4 GB")).toBeInTheDocument();
  });

  it("总量未知:不编百分比,说「大小未知」", async () => {
    renderPanel({
      texts: ["お漏らし。"],
      weights: weightsWithJa({
        status: "downloading",
        downloaded_bytes: 500_000_000,
        total_bytes: null,
        progress: 0,
      }),
    });

    const bar = await screen.findByRole("progressbar", { name: "subtitleDubModelDownloadingLabel" });
    expect(bar).not.toHaveAttribute("aria-valuenow");
    expect(bar).toHaveAttribute("aria-valuetext", "大小未知");
    expect(await screen.findByText("下载中 · 已下载 500 MB · 大小未知")).toBeInTheDocument();
    expect(screen.queryByText(/下载中 \d+%/)).toBeNull();
  });

  it("轮询本身失败:说「查不到下载状态」并给重试,不回到初始按钮", async () => {
    //: 先让第一次查询成功(正在下),再让后端 500 —— 这正是"轮询本身失败"的那一刻。
    const f5Failure = { code: 0 };
    const { client } = renderPanel({
      texts: ["お漏らし。"],
      f5Failure,
      weights: weightsWithJa({
        status: "downloading",
        downloaded_bytes: 1_000_000_000,
        total_bytes: 5_400_000_000,
      }),
    });
    await screen.findByRole("progressbar", { name: "subtitleDubModelDownloadingLabel" });

    // 之后后端连不上了(轮询失败)。这一行不能因此消失,更不能变成"什么都没发生"。
    f5Failure.code = 500;
    await act(async () => {
      await client.refetchQueries({ queryKey: ["f5-models"] }).catch(() => {});
    });

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("查不到模型下载状态");
    expect(screen.getByRole("button", { name: "重试" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "subtitleDubModelDownload" })).toBeNull();
  });
});
