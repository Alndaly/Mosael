/** @vitest-environment jsdom */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import React from "react";
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

/**
 * AI Studio「对话 | 创作」(ADR 0055):语音、播客和图像、视频、音乐在同一个创作工作台里。
 *
 * - 两个分区;深链 `#/ai?tab=create&session=…` 切到创作、开着那条会话,读完地址还原成 `#/ai`;
 * - 会话列表上面一排筛选,按种类在服务端筛;每一行带种类小标;
 * - 筛选「语音」:新的一条落在 Edge 上,输入框是要念的字,右栏是音色;交出去是 POST /api/generation/speech,回来的会话就开着;
 * - 语音记录的结果卡是带波形、取元数据的那张(不是 `preload="none"` 的 0:00);脚注是引擎名;
 * - 有记录的语音会话锁族:下拉只列语音引擎,说一句为什么;
 * - 播客三档,照稿念是逐段的编辑器:回车接下一段换人念、粘贴多行自动分段;对谈稿「改稿再念」装回编辑器;
 * - 创作页的任务列表只要挂着记录的任务(`recorded=true`)。
 */

vi.mock("@/app/preferences", () => ({
  useI18n: () => (key: string) => key,
  usePreferences: () => ({ locale: "zh-CN" }),
}));

import { AiStudio } from "@/features/ai-studio/AiStudio";
import { ImagePreviewProvider } from "@/components/app/image-preview";

beforeAll(() => {
  Object.assign(Element.prototype, {
    hasPointerCapture: () => false,
    setPointerCapture: () => {},
    releasePointerCapture: () => {},
    scrollIntoView: () => {},
  });
  globalThis.ResizeObserver ??= class {
    observe() {}
    unobserve() {}
    disconnect() {}
  } as never;
  Object.defineProperty(window, "matchMedia", {
    configurable: true,
    value: (query: string) => ({
      matches: false, media: query, onchange: null, addEventListener: () => {}, removeEventListener: () => {},
      addListener: () => {}, removeListener: () => {}, dispatchEvent: () => false,
    }),
  });
});
const originalFetch = globalThis.fetch;
afterEach(() => {
  globalThis.fetch = originalFetch;
  window.location.hash = "";
});
beforeEach(() => {
  localStorage.clear();
  localStorage.setItem("mosael:tab:ai-studio", "create");
});

const ENGINES = [
  { id: "builtin:clone", label: "本机克隆", needs_key: false, needs_voice_id: false, voices: [], supports_speed: true,
    note: "", ready: false, clones_voices: false },
  { id: "builtin:edge", label: "Edge 语音", needs_key: false, needs_voice_id: false,
    voices: ["zh-CN-XiaoxiaoNeural", "zh-CN-YunxiNeural"], supports_speed: true, note: "免费", ready: true, clones_voices: false },
  { id: "builtin:openai", label: "OpenAI 语音", needs_key: true, needs_voice_id: false, voices: ["alloy", "nova"],
    supports_speed: true, note: "", ready: true, clones_voices: false },
  { id: "builtin:volcano-podcast", label: "火山播客", needs_key: true, needs_voice_id: false,
    voices: ["voice-a", "voice-b"], supports_speed: true, note: "", ready: true, clones_voices: false },
];
const EDGE_VOICES = [
  { value: "zh-CN-XiaoxiaoNeural", label: "晓晓(女·温暖)" },
  { value: "zh-CN-YunxiNeural", label: "云希(男·阳光)" },
];
const PODCAST_VOICES = [{ value: "voice-a", label: "大壹先生" }, { value: "voice-b", label: "咪仔同学" }];
const IMAGE_OPTION = {
  id: "p1:image:gpt-image-1", provider_profile_id: "p1", profile_name: "OpenAI", provider: "openai", kind: "image",
  model: "gpt-image-1", model_label: "gpt-image-1", capabilities: { modes: ["text-to-image"], parameter_keys: [] },
  capabilities_known: true, adapter_available: true, is_default: true,
};

function sessionRow(id: string, kind: string, title: string, model = "") {
  return { id, workspace_id: "w1", title, kind, provider_profile_id: null, model, is_mine: true, shared: false,
           created_at: "2026-10-08T00:00:00Z", updated_at: "2026-10-08T00:00:00Z" };
}

function speechRecord(overrides: Record<string, unknown> = {}) {
  return {
    id: "g-speech", workspace_id: "w1", session_id: "s-speech", job_id: null, provider_profile_id: null,
    provider: "builtin:edge", model: "zh-CN-XiaoxiaoNeural", kind: "speech",
    request: { prompt: "欢迎来到 Mosael", voice: "zh-CN-XiaoxiaoNeural", voice_label: "晓晓(女·温暖)", engine_label: "Edge 语音", speed: 1 },
    result_asset_id: "a-speech", result_asset_ids: ["a-speech"], error: null, error_summary: null, stopped: false,
    retrievable: false, costs: [], cost_confidence: "free",
    created_at: "2026-10-08T00:00:00Z", updated_at: "2026-10-08T00:00:03Z",
    ...overrides,
  };
}

function renderStudio({
  sessions = [] as unknown[],
  records = {} as Record<string, unknown[]>,
  assets = {} as Record<string, unknown>,
  jobs = [] as unknown[],
  respond = (url: string): unknown => (url.includes("/api/generation/speech") || url.includes("/api/generation/podcast")
    ? { generation: { id: "g-new", session_id: "s-made" }, job: { id: "j-new", status: "queued" } }
    : {}),
} = {}) {
  const posts: Array<{ url: string; method: string; body: Record<string, unknown> | null }> = [];
  const gets: string[] = [];
  globalThis.fetch = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    const json = (body: unknown) => new Response(JSON.stringify(body), { status: 200, headers: { "content-type": "application/json" } });
    if (init?.method && init.method !== "GET") {
      posts.push({ url, method: init.method, body: init.body ? JSON.parse(String(init.body)) : null });
      return json(respond(url));
    }
    gets.push(url);
    if (url.includes("/api/generation/options?kind=image")) return json([IMAGE_OPTION]);
    if (url.includes("/api/generation/options")) return json([]);
    if (url.includes("/api/generation/sessions")) {
      const kind = new URL(url, "http://x").searchParams.get("kind");
      return json(kind ? (sessions as { kind: string }[]).filter((one) => one.kind === kind) : sessions);
    }
    if (url.includes("/api/generation/jobs")) {
      const session = new URL(url, "http://x").searchParams.get("session_id") ?? "";
      return json(records[session] ?? []);
    }
    if (url.includes("/api/tts/engines")) return json(ENGINES);
    if (url.includes("/api/tts/voices")) {
      return json(url.includes("volcano-podcast") ? PODCAST_VOICES
        : url.includes("openai") ? [{ value: "alloy", label: "alloy" }, { value: "nova", label: "nova" }] : EDGE_VOICES);
    }
    if (url.includes("/api/tts/models")) return json([]);
    if (url.includes("/api/tts/config")) return json({ engine: "f5-tts" });
    if (url.includes("/api/jobs")) return json(jobs);
    const asset = /\/api\/assets\/([^/?]+)$/.exec(url);
    if (asset && assets[asset[1]]) return json(assets[asset[1]]);
    return json([]);
  }) as never;
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <ImagePreviewProvider>
        <AiStudio workspace={{ id: "w1", name: "W" } as never} />
      </ImagePreviewProvider>
    </QueryClientProvider>,
  );
  return { posts, gets };
}

describe("两个分区和深链", () => {
  it("顶上是「对话 | 创作」两个分区", async () => {
    renderStudio();
    const tabs = within(screen.getByRole("tablist", { name: "AI Studio" })).getAllByRole("tab");
    expect(tabs.map((tab) => tab.textContent)).toEqual(["aiTabChat", "aiTabCreate"]);
    expect(tabs[1]).toHaveAttribute("aria-selected", "true");
  });

  it("#/ai?tab=create&session=…:切到创作、开着那条会话、筛选回到全部,地址还原成 #/ai", async () => {
    localStorage.setItem("mosael:tab:ai-studio", "chat");
    localStorage.setItem("mosael:tab:ai-studio-create-filter", "image");
    window.location.hash = "#/ai?tab=create&session=s-speech";
    renderStudio({ sessions: [sessionRow("s-speech", "speech", "产品旁白", "builtin:edge")], records: { "s-speech": [speechRecord()] } });
    expect(await screen.findByRole("textbox", { name: "createSpeechLabel" })).toBeInTheDocument();
    expect(window.location.hash).toBe("#/ai");
    expect(screen.getByRole("tab", { name: /createFilterAll/ })).toHaveAttribute("aria-selected", "true");
    expect(localStorage.getItem("mosael.generation.session.w1.create")).toBe("s-speech");
  });
});

describe("筛选与会话小标", () => {
  it("一排筛选按种类在服务端筛,选过的记在本机;每行带种类小标", async () => {
    const user = userEvent.setup();
    const { gets } = renderStudio({
      sessions: [sessionRow("s1", "image", "森林海报"), sessionRow("s2", "speech", "产品旁白", "builtin:edge"),
                 sessionRow("s3", "podcast", "两人聊 AI", "builtin:volcano-podcast")],
    });
    const row = await screen.findByRole("button", { name: /产品旁白/ });
    expect(row.querySelector("[data-kind-badge='speech']")?.textContent).toBe("createKindSpeech");
    expect(screen.getByRole("button", { name: /森林海报/ }).querySelector("[data-kind-badge='image']")).toBeTruthy();

    await user.click(screen.getByRole("tab", { name: /createKindPodcast/ }));
    await waitFor(() => expect(gets.some((url) => url.includes("/api/generation/sessions") && url.includes("&kind=podcast"))).toBe(true));
    await waitFor(() => expect(screen.queryByRole("button", { name: /产品旁白/ })).toBeNull());
    expect(screen.getByRole("button", { name: /两人聊 AI/ })).toBeInTheDocument();
    expect(localStorage.getItem("mosael:tab:ai-studio-create-filter")).toBe("podcast");
  });

  it("这一种还没有会话:按种类说下一步做什么", async () => {
    localStorage.setItem("mosael:tab:ai-studio-create-filter", "speech");
    renderStudio();
    expect(await screen.findByText("createEmptySpeech")).toBeInTheDocument();
  });

  it("创作页的任务列表只要挂着记录的那些", async () => {
    const { gets } = renderStudio();
    await waitFor(() => expect(gets.some((url) => url.includes("/api/jobs?"))).toBe(true));
    expect(gets.filter((url) => url.includes("/api/jobs?")).every((url) => url.includes("recorded=true"))).toBe(true);
    expect(gets.some((url) => url.includes("kind=ai_generation"))).toBe(false);
  });
});

describe("语音", () => {
  it("筛选「语音」的新一条:落在 Edge 上,写字、挑音色,交出去是 /api/generation/speech,回来的会话就开着", async () => {
    const user = userEvent.setup();
    localStorage.setItem("mosael:tab:ai-studio-create-filter", "speech");
    const { posts } = renderStudio();
    const text = await screen.findByRole("textbox", { name: "createSpeechLabel" });
    //: 引擎那枚按钮写的是 Edge(内置、免费 —— 不替人挑一个要钱的)
    await waitFor(() => expect(document.querySelector("[data-engine-chip]")?.textContent).toContain("Edge 语音"));
    //: 右栏是音色,不是图像那几栏
    expect(screen.getByRole("complementary", { name: "generationEngineSettings" }).querySelector("[data-speech-voice]")).toBeTruthy();
    expect(screen.queryByText("genSectionOutput")).toBeNull();
    const send = screen.getByRole("button", { name: "generate" });
    expect(send).toBeDisabled();
    await user.type(text, "欢迎来到 Mosael");
    expect(document.querySelector("[data-voiced-count]")?.textContent).toBe("createSpeechCount");
    await waitFor(() => expect(send).toBeEnabled());
    await user.click(send);
    await waitFor(() => expect(posts.some((one) => one.url.endsWith("/api/generation/speech"))).toBe(true));
    const body = posts.find((one) => one.url.endsWith("/api/generation/speech"))!.body!;
    expect(body).toMatchObject({
      workspace_id: "w1", session_id: null, text: "欢迎来到 Mosael", engine: "builtin:edge",
      voice: "zh-CN-XiaoxiaoNeural", voice_label: "晓晓(女·温暖)", engine_label: "Edge 语音",
    });
    expect(posts.some((one) => one.url.endsWith("/api/generation/jobs")), "不走图像那条路").toBe(false);
    expect(posts.some((one) => one.url.endsWith("/api/generation/sessions")), "会话由后端现开").toBe(false);
    await waitFor(() => expect(localStorage.getItem("mosael.generation.session.w1.create")).toBe("s-made"));
    expect((text as HTMLTextAreaElement).value).toBe("");
  });

  it("语音记录:结果卡带波形、取元数据(不是 preload=none 的 0:00),标题是音色名,脚注是引擎名", async () => {
    localStorage.setItem("mosael.generation.session.w1.create", "s-speech");
    renderStudio({ sessions: [sessionRow("s-speech", "speech", "产品旁白", "builtin:edge")], records: { "s-speech": [speechRecord()] } });
    const track = await waitFor(() => {
      const found = document.querySelector("[data-audio-track='a-speech']");
      expect(found).toBeTruthy();
      return found as HTMLElement;
    });
    expect(track.querySelector("audio")).toHaveAttribute("preload", "metadata");
    expect(track.textContent).toContain("晓晓(女·温暖)");
    expect(document.querySelector("[data-engine-name]")?.textContent).toBe("Edge 语音");
    //: 用户气泡是念的字
    expect(screen.getByText("欢迎来到 Mosael")).toBeInTheDocument();
  });

  it("打开一条语音会话:右栏停在最后一条用的音色上;在右栏换一个,交出去的就是换过的", async () => {
    const user = userEvent.setup();
    localStorage.setItem("mosael.generation.session.w1.create", "s-speech");
    const { posts } = renderStudio({
      sessions: [sessionRow("s-speech", "speech", "产品旁白", "builtin:edge")],
      records: { "s-speech": [speechRecord(), speechRecord({ id: "g-2", model: "zh-CN-YunxiNeural",
        request: { prompt: "第二段", voice: "zh-CN-YunxiNeural", voice_label: "云希(男·阳光)", speed: 1.25 } })] },
    });
    const panel = screen.getByRole("complementary", { name: "generationEngineSettings" });
    const picker = () => within(panel).getByRole("combobox", { name: "voiceEngineVoice" });
    await waitFor(() => expect(picker()).toHaveTextContent("云希(男·阳光)"));
    expect(within(panel).getByRole("combobox", { name: "voiceSpeed" })).toHaveTextContent("1.25");
    await user.click(picker());
    await user.click(await screen.findByRole("option", { name: "晓晓(女·温暖)" }));
    await waitFor(() => expect(picker()).toHaveTextContent("晓晓(女·温暖)"));
    await user.type(screen.getByRole("textbox", { name: "createSpeechLabel" }), "第三段");
    //: 打几个字(重渲染好几次)之后音色还在
    expect(picker()).toHaveTextContent("晓晓(女·温暖)");
    await user.click(screen.getByRole("button", { name: "generate" }));
    await waitFor(() => expect(posts.some((one) => one.url.endsWith("/api/generation/speech"))).toBe(true));
    expect(posts.find((one) => one.url.endsWith("/api/generation/speech"))!.body).toMatchObject({
      session_id: "s-speech", voice: "zh-CN-XiaoxiaoNeural", voice_label: "晓晓(女·温暖)", speed: 1.25,
    });
  });

  it("在两条用不同引擎的语音会话之间来回切:回到那条(记录已经在缓存里)时音色还是它自己的", async () => {
    const user = userEvent.setup();
    localStorage.setItem("mosael.generation.session.w1.create", "s-other");
    renderStudio({
      sessions: [sessionRow("s-other", "speech", "另一个引擎", "builtin:openai"), sessionRow("s-speech", "speech", "产品旁白", "builtin:edge")],
      records: {
        "s-other": [speechRecord({ id: "g-o", session_id: "s-other", provider: "builtin:openai", model: "nova",
                                   request: { prompt: "hi", voice: "nova", voice_label: "nova" } })],
        "s-speech": [speechRecord()],
      },
    });
    const panel = screen.getByRole("complementary", { name: "generationEngineSettings" });
    const picker = () => within(panel).getByRole("combobox", { name: "voiceEngineVoice" });
    await waitFor(() => expect(picker()).toHaveTextContent("nova"));
    await user.click(screen.getByRole("button", { name: /产品旁白/ }));
    await waitFor(() => expect(picker()).toHaveTextContent("晓晓(女·温暖)"));
    await user.click(screen.getByRole("button", { name: /另一个引擎/ }));
    await waitFor(() => expect(picker()).toHaveTextContent("nova"));
    //: 再渲染几次(打几个字):引擎那一下重设如果再跑一遍,会把它清回第一个
    await user.type(screen.getByRole("textbox", { name: "createSpeechLabel" }), "abc");
    expect(picker()).toHaveTextContent("nova");
  });

  it("有记录的语音会话锁族:下拉只列语音引擎,说一句为什么", async () => {
    const user = userEvent.setup();
    localStorage.setItem("mosael.generation.session.w1.create", "s-speech");
    renderStudio({ sessions: [sessionRow("s-speech", "speech", "产品旁白", "builtin:edge")], records: { "s-speech": [speechRecord()] } });
    await screen.findByRole("textbox", { name: "createSpeechLabel" });
    await waitFor(() => expect(document.querySelector("[data-family-locked]")?.textContent).toBe("createFamilyLocked"));
    await user.click(document.querySelector<HTMLElement>("[data-engine-picker] button")!);
    const listbox = await screen.findByRole("listbox");
    expect(within(listbox).getByText("Edge 语音")).toBeInTheDocument();
    expect(within(listbox).queryByText("gpt-image-1")).toBeNull();
    expect(within(listbox).queryByText("火山播客")).toBeNull();
  });

  it("挑了本机克隆而配音库里一把嗓子都没有:右栏用提示条说去哪录(不是虚线大框)", async () => {
    const user = userEvent.setup();
    localStorage.setItem("mosael:tab:ai-studio-create-filter", "speech");
    renderStudio();
    await screen.findByRole("textbox", { name: "createSpeechLabel" });
    await user.click(document.querySelector<HTMLElement>("[data-engine-picker] button")!);
    await user.click(await screen.findByRole("option", { name: /本机克隆/ }));
    const panel = screen.getByRole("complementary", { name: "generationEngineSettings" });
    expect(await within(panel).findByText("audioCloneNeedsVoice")).toBeInTheDocument();
    expect(within(panel).getByRole("button", { name: /audioManageVoices/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "generate" })).toBeDisabled();
  });

  it("老版本迁过来、只剩开头的:气泡下说一句", async () => {
    localStorage.setItem("mosael.generation.session.w1.create", "s-speech");
    renderStudio({
      sessions: [sessionRow("s-speech", "speech", "以前的语音", "builtin:edge")],
      records: { "s-speech": [speechRecord({ request: { prompt: "很长的一段", voice: "zh-CN-XiaoxiaoNeural", truncated: true } })] },
    });
    expect(await screen.findByText("createTruncated")).toBeInTheDocument();
    //: 没记音色名的老记录:标题从引擎的音色目录里认
    await waitFor(() => expect(document.querySelector("[data-audio-track='a-speech']")?.textContent).toContain("晓晓(女·温暖)"));
  });

  it("念着的那一条有「停止」:取消它的任务;停下的说「已停止」", async () => {
    const user = userEvent.setup();
    localStorage.setItem("mosael.generation.session.w1.create", "s-speech");
    const running = speechRecord({ job_id: "j-run", result_asset_id: null, result_asset_ids: [], cost_confidence: null });
    const { posts } = renderStudio({
      sessions: [sessionRow("s-speech", "speech", "产品旁白", "builtin:edge")],
      records: { "s-speech": [running, speechRecord({ id: "g-stopped", job_id: null, result_asset_id: null, result_asset_ids: [],
                                                        error: "已取消", stopped: true })] },
      jobs: [{ id: "j-run", kind: "tts", status: "running", progress: 0.4, message: "", payload: {}, result: {},
               error: null, created_at: "2026-10-08T00:00:00Z", updated_at: "2026-10-08T00:00:01Z", workspace_id: "w1" }],
    });
    const pending = await waitFor(() => {
      const found = document.querySelector("[data-generation-status='running']");
      expect(found).toBeTruthy();
      return found as HTMLElement;
    });
    //: 念着的占位和音乐同一个壳(一张音频卡),不是画面的灰框
    expect(pending.querySelector("[data-generation-pending] ul[aria-hidden] li")).toBeTruthy();
    await user.click(within(pending).getByRole("button", { name: /genStop/ }));
    await waitFor(() => expect(posts.some((one) => one.url.includes("/api/jobs/j-run/cancel"))).toBe(true));
    expect(document.querySelector("[data-generation-status='stopped']")).toBeTruthy();
  });
});

describe("播客", () => {
  it("照稿念:回车接下一段换人念,粘贴多行自动分段;交出去的是逐段的稿子和两位发音人", async () => {
    const user = userEvent.setup();
    localStorage.setItem("mosael:tab:ai-studio-create-filter", "podcast");
    const { posts } = renderStudio();
    await user.click(await screen.findByRole("tab", { name: "createPodcastModeRead" }));
    const first = screen.getByRole("textbox", { name: "createScriptTurnLabel" });
    await user.type(first, "大家好{Enter}");
    const turns = () => [...document.querySelectorAll<HTMLElement>("[data-script-turn]")];
    expect(turns().map((one) => one.dataset.scriptTurn)).toEqual(["0", "1"]);
    const second = turns()[1].querySelector("textarea")!;
    fireEvent.paste(second, { clipboardData: { getData: () => "B:今天聊聊 AI 剪辑\n大壹先生:先说结论\n最后一句" } });
    await waitFor(() => expect(turns().map((one) => one.dataset.scriptTurn)).toEqual(["0", "1", "0", "1"]));
    //: 最后多回车出一段空的:交出去时不带它
    await user.click(screen.getByRole("button", { name: "createScriptAddTurn" }));
    expect(turns()).toHaveLength(5);
    expect(document.querySelector("[data-voiced-count]")?.textContent).toBe("createScriptTurns");
    const send = screen.getByRole("button", { name: "generate" });
    await waitFor(() => expect(send).toBeEnabled());
    await user.click(send);
    await waitFor(() => expect(posts.some((one) => one.url.endsWith("/api/generation/podcast"))).toBe(true));
    expect((posts.find((one) => one.url.endsWith("/api/generation/podcast"))!.body as { turns: unknown[] }).turns).toHaveLength(4);
    expect(posts.find((one) => one.url.endsWith("/api/generation/podcast"))!.body).toMatchObject({
      mode: "read",
      turns: [
        { speaker: 0, text: "大家好" }, { speaker: 1, text: "今天聊聊 AI 剪辑" },
        { speaker: 0, text: "先说结论" }, { speaker: 1, text: "最后一句" },
      ],
      speakers: [{ value: "voice-a", label: "大壹先生" }, { value: "voice-b", label: "咪仔同学" }],
    });
  });

  it("聊一个主题:一行主题,两位发音人在右栏(各带试听)", async () => {
    const user = userEvent.setup();
    localStorage.setItem("mosael:tab:ai-studio-create-filter", "podcast");
    const { posts } = renderStudio();
    await user.click(await screen.findByRole("tab", { name: "createPodcastModeResearch" }));
    await user.type(screen.getByRole("textbox", { name: "createPodcastTopicLabel" }), "AI 剪辑的未来");
    const panel = screen.getByRole("complementary", { name: "generationEngineSettings" });
    expect(within(panel).getAllByRole("button", { name: "voicePreview" })).toHaveLength(2);
    await user.click(screen.getByRole("button", { name: "generate" }));
    await waitFor(() => expect(posts.some((one) => one.url.endsWith("/api/generation/podcast"))).toBe(true));
    expect(posts.find((one) => one.url.endsWith("/api/generation/podcast"))!.body).toMatchObject({
      mode: "research", text: "AI 剪辑的未来",
    });
  });

  it("做好的播客:对谈稿收着、按发音人标名字;「改稿再念」把稿子装回照稿念", async () => {
    const user = userEvent.setup();
    localStorage.setItem("mosael.generation.session.w1.create", "s-pod");
    renderStudio({
      sessions: [sessionRow("s-pod", "podcast", "两人聊 AI", "builtin:volcano-podcast")],
      records: { "s-pod": [{
        ...speechRecord(), id: "g-pod", session_id: "s-pod", kind: "podcast", provider: "builtin:volcano-podcast", model: "dialogue",
        //: 老版本迁过来的:没记发音人的名字,从播客的发音人目录里认
        request: { mode: "research", prompt: "AI 剪辑", speakers: [{ value: "voice-a", label: "" }, { value: "voice-b", label: "" }] },
        result_asset_id: "a-pod", result_asset_ids: ["a-pod"],
      }] },
      assets: { "a-pod": { id: "a-pod", name: "AI 剪辑 · 播客", kind: "audio", media_info: {
        dialogue: [{ speaker: "voice-b", text: "我先说" }, { speaker: "voice-a", text: "好" }],
      } } },
    });
    const toggle = await screen.findByRole("button", { name: /createDialogueShow/ });
    await user.click(toggle);
    const dialogue = document.querySelector("[data-podcast-dialogue]")!;
    await waitFor(() => expect(dialogue.textContent).toContain("咪仔同学"));
    expect(dialogue.textContent).not.toContain("voice-b");
    expect(dialogue.textContent).toContain("我先说");
    await user.click(within(dialogue as HTMLElement).getByRole("button", { name: /createRescript/ }));
    await waitFor(() => expect(screen.getByRole("tab", { name: "createPodcastModeRead" })).toHaveAttribute("aria-selected", "true"));
    const rows = [...document.querySelectorAll<HTMLElement>("[data-script-turn]")];
    expect(rows.map((one) => [one.dataset.scriptTurn, one.querySelector("textarea")!.value])).toEqual([["1", "我先说"], ["0", "好"]]);
  });
});

it("会话在别处被打开(任务中心「前往」):创作页收到就开着它", async () => {
  const { emitOpenEvent } = await import("@/lib/deepLink");
  localStorage.setItem("mosael:tab:ai-studio", "chat");
  renderStudio({ sessions: [sessionRow("s-speech", "speech", "产品旁白", "builtin:edge")], records: { "s-speech": [speechRecord()] } });
  act(() => emitOpenEvent("mosael:open-creation-session", "s-speech"));
  expect(await screen.findByRole("textbox", { name: "createSpeechLabel" })).toBeInTheDocument();
  expect(localStorage.getItem("mosael:tab:ai-studio")).toBe("create");
});
