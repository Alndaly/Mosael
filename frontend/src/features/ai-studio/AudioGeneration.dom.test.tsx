/** @vitest-environment jsdom */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import React from "react";
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

/**
 * AI 生成里的**音频**(音乐、BGM、音效,ADR 0022):和图像、视频同一条生成管线、同一个会话工作台,但在
 * 「音频」页的「音乐与音效」里 —— 找音乐的人进的是「音频」页。只多两样:歌词编辑器和纯音乐开关;结果是
 * 一段(或几段)声音,不是缩略图。
 *
 * 钉住的是:音乐音效在「音频」页、只列音频模型和音频会话,「生成」页不再列它们;选了音频模型才长出歌词栏;
 * 只给歌词不给描述也能提交,发出去的是 kind=audio 和歌词;纯音乐时歌词栏灰掉、不发歌词;一次交回两首时
 * 两首都有播放器。
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
      matches: false,
      media: query,
      onchange: null,
      addEventListener: () => {},
      removeEventListener: () => {},
      addListener: () => {},
      removeListener: () => {},
      dispatchEvent: () => false,
    }),
  });
});
const originalFetch = globalThis.fetch;
afterEach(() => {
  globalThis.fetch = originalFetch;
});
beforeEach(() => {
  localStorage.clear();
  // 直接落在「音频」页的「音乐与音效」。
  localStorage.setItem("mosael:tab:ai-studio", "create");
  localStorage.setItem("mosael:tab:ai-studio-create-filter", "audio");
  //: 上次开着的是 s1(没选过会话时停在「新的一条」,见 UC-03)
  localStorage.setItem("mosael.generation.session.w1.create", "s1");
});

function audioOption(capabilities: Record<string, unknown>) {
  return {
    id: "p1:audio:suno-v5-beta",
    provider_profile_id: "p1",
    profile_name: "Evolink",
    provider: "evolink",
    kind: "audio",
    model: "suno-v5-beta",
    label: "Evolink · suno-v5-beta",
    capabilities,
    capabilities_known: true,
    adapter_available: true,
    is_default: true,
  };
}

const SUNO = {
  modes: ["text-to-music", "lyrics-to-song", "text-to-bgm"],
  parameter_keys: ["lyrics", "instrumental", "negative_prompt", "title", "vocal_gender"],
  boolean_parameters: ["instrumental"],
  default_instrumental: false,
  max_prompt_chars: 500,
  max_lyrics_chars: 5000,
  outputs_per_request: 2,
  parameter_schema: {
    title: { type: "string", title: "Title" },
    vocal_gender: { type: "string", enum: ["female", "male"], title: "Vocal gender" },
  },
};

const SESSION = { id: "s1", workspace_id: "w1", title: "会话", origin_kind: "studio", origin_id: "", origin_name: "", origin_state: "ok", created_at: "2026-09-01T00:00:00Z", updated_at: "2026-09-01T00:00:00Z" };

function renderStudio({
  capabilities = SUNO as Record<string, unknown>,
  generations = [] as unknown[],
  jobs = [] as unknown[],
} = {}) {
  const posts: Array<{ url: string; body: Record<string, unknown> }> = [];
  const gets: string[] = [];
  globalThis.fetch = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    if (!init?.method || init.method === "GET") gets.push(url);
    const json = (body: unknown) => new Response(JSON.stringify(body), { status: 200, headers: { "content-type": "application/json" } });
    if (init?.method === "POST") {
      posts.push({ url, body: JSON.parse(String(init.body)) });
      return json({ generation: { id: "g-new" }, job: { id: "j-new", status: "queued" } });
    }
    if (init?.method === "PATCH") return json(SESSION);
    if (url.includes("/api/generation/options?kind=audio")) return json([audioOption(capabilities)]);
    if (url.includes("/api/generation/options")) return json([]);
    if (url.includes("/api/generation/sessions")) return json([SESSION]);
    if (url.includes("/api/generation/jobs")) return json(generations);
    if (url.includes("/api/settings/providers")) return json([{ id: "p1", name: "Evolink", vendor: "evolink", enabled: true }]);
    if (url.includes("/api/jobs")) return json(jobs);
    return json([]);
  }) as never;
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <ImagePreviewProvider>
        <AiStudio workspace={{ id: "w1", name: "W", role: "editor" } as never} />
      </ImagePreviewProvider>
    </QueryClientProvider>,
  );
  return { posts, gets };
}

describe("音频生成的控件", () => {
  it("选了音频模型:长出歌词栏和人声开关;只给歌词也能提交,发的是 kind=audio 和歌词", async () => {
    const user = userEvent.setup();
    const { posts } = renderStudio();
    const lyrics = await screen.findByRole("textbox", { name: "genLyrics" });
    expect(screen.getByRole("combobox", { name: "genInstrumental" })).toBeInTheDocument();
    // 提示词框换成音频的说法
    expect(screen.getByRole("textbox", { name: "genPromptLabel" })).toHaveAttribute("placeholder", "audioPromptPlaceholder");
    // 空态正文也换成音频的说法,不再是「描述你想生成的画面」
    await waitFor(() => expect(screen.getByText("audioPromptPlaceholder")).toBeInTheDocument());
    expect(screen.queryByText("promptPlaceholder")).toBeNull();
    // 什么字都没有时不能提交
    const submit = screen.getByRole("button", { name: "generate" });
    expect(submit).toBeDisabled();

    // user-event 里 `[` 是按键描述的开头,字面的方括号写成 `[[`。
    await user.type(lyrics, "[[Verse] 啦啦啦");
    // 字数与上限
    expect(screen.getByText("11 / 5000")).toBeInTheDocument();
    await waitFor(() => expect(submit).toBeEnabled());
    await user.click(submit);

    await waitFor(() => expect(posts.some((one) => one.url.includes("/api/generation/jobs"))).toBe(true));
    const sent = posts.find((one) => one.url.includes("/api/generation/jobs"))!.body;
    expect(sent).toMatchObject({ kind: "audio", model: "suno-v5-beta", provider: "evolink", prompt: "" });
    expect(sent.parameters).toEqual({ instrumental: false, lyrics: "[Verse] 啦啦啦" });
  });

  it("纯音乐:歌词栏灰掉并说明为什么,发出去的只有纯音乐开关", async () => {
    const user = userEvent.setup();
    const { posts } = renderStudio({ capabilities: { ...SUNO, default_instrumental: true } });
    const lyrics = await screen.findByRole("textbox", { name: "genLyrics" });
    expect(lyrics).toBeDisabled();
    expect(screen.getByText("genLyricsInstrumentalHint")).toBeInTheDocument();
    await user.type(screen.getByRole("textbox", { name: "genPromptLabel" }), "lofi 钢琴");
    await user.click(screen.getByRole("button", { name: "generate" }));
    await waitFor(() => expect(posts.some((one) => one.url.includes("/api/generation/jobs"))).toBe(true));
    const sent = posts.find((one) => one.url.includes("/api/generation/jobs"))!.body;
    expect(sent).toMatchObject({ kind: "audio", prompt: "lofi 钢琴" });
    expect(sent.parameters).toEqual({ instrumental: true });
  });

  it("模型自己声明的曲名、人声按界面语言命名,不显示插件/目录里的英文 title", async () => {
    renderStudio();
    await screen.findByRole("textbox", { name: "genLyrics" });
    expect(screen.getByText("genSongTitle")).toBeInTheDocument();
    expect(screen.getByText("genVocalGender")).toBeInTheDocument();
    expect(screen.queryByText("Vocal gender")).toBeNull();
  });

  it("时长可以空着:区间型的音频时长是个数字框,占位是「自动」,不会被悄悄填成最小值", async () => {
    const user = userEvent.setup();
    const { posts } = renderStudio({
      capabilities: {
        ...SUNO,
        parameter_keys: [...SUNO.parameter_keys, "duration_seconds"],
        duration_seconds: [],
        min_duration_seconds: 10,
        max_duration_seconds: 360,
      },
    });
    const duration = (await screen.findByRole("spinbutton", { name: "genDuration" })) as HTMLInputElement;
    expect(duration.value).toBe("");
    expect(duration.placeholder).toBe("genDurationAuto");
    expect(duration.min).toBe("10");
    expect(duration.max).toBe("360");
    await user.type(screen.getByRole("textbox", { name: "genPromptLabel" }), "city pop");
    await user.click(screen.getByRole("button", { name: "generate" }));
    await waitFor(() => expect(posts.some((one) => one.url.includes("/api/generation/jobs"))).toBe(true));
    const sent = posts.find((one) => one.url.includes("/api/generation/jobs"))!.body;
    expect(sent.parameters).not.toHaveProperty("duration_seconds");
  });
});

describe("音乐在创作页的「音乐」筛选里(ADR 0055)", () => {
  it("会话按 kind=audio 在服务端筛;新会话记成音频", async () => {
    const user = userEvent.setup();
    const { posts, gets } = renderStudio();
    await screen.findByRole("textbox", { name: "genLyrics" });
    expect(screen.getByRole("tab", { name: /createKindAudio/ })).toHaveAttribute("aria-selected", "true");
    expect(gets.some((url) => url.includes("/api/generation/sessions") && url.includes("&kind=audio"))).toBe(true);
    expect(gets.some((url) => url.includes("/api/generation/sessions") && url.includes("kind=image"))).toBe(false);

    //: 「+」换成新的一条,不在服务端建空会话;第一次提交才建,记成音频、记下用的模型(UC-10)
    await user.click(screen.getByRole("button", { name: "generationNewSession" }));
    expect(posts.some((one) => one.url.endsWith("/api/generation/sessions")), "点「+」不建").toBe(false);
    await user.type(screen.getByRole("textbox", { name: "genPromptLabel" }), "city pop");
    await user.click(screen.getByRole("button", { name: "generate" }));
    await waitFor(() => expect(posts.some((one) => one.url.endsWith("/api/generation/sessions"))).toBe(true));
    expect(posts.find((one) => one.url.endsWith("/api/generation/sessions"))!.body).toMatchObject({
      kind: "audio", provider_profile_id: "p1", model: "suno-v5-beta" });
  });

  it("「全部」:会话不按种类筛,三种生成模型都拉;点「音乐」只看音乐会话", async () => {
    const user = userEvent.setup();
    localStorage.setItem("mosael:tab:ai-studio-create-filter", "all");
    const { gets } = renderStudio();
    await waitFor(() => expect(gets.some((url) => url.includes("/api/generation/options?kind=audio"))).toBe(true));
    for (const kind of ["image", "video"]) expect(gets.some((url) => url.includes(`/api/generation/options?kind=${kind}`))).toBe(true);
    expect(gets.some((url) => url.includes("/api/generation/sessions") && !url.includes("kind="))).toBe(true);
    await user.click(screen.getByRole("tab", { name: /createKindAudio/ }));
    await waitFor(() => expect(gets.some((url) => url.includes("/api/generation/sessions") && url.includes("&kind=audio"))).toBe(true));
    expect(localStorage.getItem("mosael:tab:ai-studio-create-filter")).toBe("audio");
  });
});

describe("音频生成的结果", () => {
  it("一次交回两首:两首都有播放器,按交回的顺序", async () => {
    renderStudio({
      generations: [
        {
          id: "g1",
          workspace_id: "w1",
          session_id: "s1",
          job_id: "j1",
          provider_profile_id: "p1",
          provider: "evolink",
          model: "suno-v5-beta",
          kind: "audio",
          request: { prompt: "夏夜城市流行", parameters: {} },
          result_asset_id: "a1",
          result_asset_ids: ["a1", "a2"],
          created_at: "2026-09-01T00:00:00Z",
          updated_at: "2026-09-01T00:01:00Z",
          costs: [],
          cost_confidence: null,
        },
      ],
      jobs: [{ id: "j1", status: "succeeded", kind: "ai_generation", progress: 1, created_at: "2026-09-01T00:00:00Z", updated_at: "2026-09-01T00:01:00Z" }],
    });
    const list = await screen.findByRole("list", { name: "genAudioResults" });
    const items = within(list).getAllByRole("listitem");
    expect(items).toHaveLength(2);
    const players = list.querySelectorAll("audio");
    expect(players).toHaveLength(2);
    expect(players[0].getAttribute("src")).toContain("a1");
    expect(players[1].getAttribute("src")).toContain("a2");
    expect(within(items[1]).getByText(/genAudioTrack/)).toBeInTheDocument();
    // 不是缩略图
    expect(list.querySelector("img")).toBeNull();
  });

  //: 维护者:「音频生成的这里卡片 UI 太丑了 避免使用这种原生组件」—— 每一首是全站同一套播放机件拼的卡片
  it("每一首是应用自己的播放卡:播放、进度、时长、静音、保存到本地、在素材库里打开 —— 不是浏览器自带的控件条", async () => {
    renderStudio({
      generations: [
        {
          id: "g1", workspace_id: "w1", session_id: "s1", job_id: null, provider_profile_id: "p1", provider: "evolink",
          model: "suno-v5-beta", kind: "audio", request: { prompt: "夏夜城市流行", parameters: {} }, result_asset_id: "a1",
          result_asset_ids: ["a1", "a2"], created_at: "2026-09-01T00:00:00Z", updated_at: "2026-09-01T00:01:00Z",
          costs: [], cost_confidence: null,
        },
      ],
    });
    const list = await screen.findByRole("list", { name: "genAudioResults" });
    expect(list.querySelector("audio[controls]"), "浏览器自带的那一条").toBeNull();
    const [first] = within(list).getAllByRole("listitem");
    for (const name of ["boardPlay", "boardMute", "assetSaveLocal", "documentOpenAsset"]) {
      expect(within(first).getByRole("button", { name })).toBeInTheDocument();
    }
    expect(within(first).getByRole("slider", { name: "mediaSeek" })).toBeInTheDocument();
    expect(first.textContent).toContain("0:00 / 0:00");
    fireEvent.click(within(first).getByRole("button", { name: "documentOpenAsset" }));
    expect(window.location.hash).toBe("#/media");
  });
});
