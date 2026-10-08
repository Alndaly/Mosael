/** @vitest-environment jsdom */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen, waitFor } from "@testing-library/react";
import React from "react";
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

/**
 * 首次加载的骨架和真内容**同一套外壳**(维护者:「不同的模式应该是不一样的 Skeleton,且实际位置似乎和真实的不一样」)。
 *
 * jsdom 不排版,这里钉的是「外框是同一个」:骨架那一轮的整轮、提示词气泡、结果那一行、脚注,和记录到了之后真的那一轮
 * className 一字不差;结果那一格按会话的种类画 —— 视频是和成片同一个 16:9 框、音频类是和结果卡同一个壳、图是一张最高 360px
 * 的图框;对话那一侧的骨架用的是真气泡的那几个类。浏览器里量到的位移写在交回报告里。
 */

vi.mock("@/app/preferences", () => ({
  useI18n: () => (key: string) => key,
  usePreferences: () => ({ locale: "zh-CN" }),
}));

import { AiStudio } from "@/features/ai-studio/AiStudio";
import { ImagePreviewProvider } from "@/components/app/image-preview";
import { ChatBubble } from "@/features/agent/ChatBubble";
import { ChatTranscriptSkeleton } from "@/features/agent/chatSkeleton";
import { TraceStatsBar } from "@/features/agent/trace/TraceView";
import { buildTurns } from "@/features/agent/trace/traceModel";

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
});
beforeEach(() => {
  localStorage.clear();
  localStorage.setItem("mosael:tab:ai-studio", "create");
  localStorage.setItem("mosael.generation.session.w1.create", "s1");
});

const RECORD = {
  id: "g1", workspace_id: "w1", session_id: "s1", job_id: null, provider_profile_id: "p1", provider: "openai",
  model: "m", request: { prompt: "一张海报" }, result_asset_id: "a1", result_asset_ids: ["a1"], error: null,
  error_summary: null, stopped: false, retrievable: false, costs: [], cost_confidence: null,
  created_at: "2026-10-08T00:00:00Z", updated_at: "2026-10-08T00:00:05Z",
};

/** 记录那一路先挂着不回:骨架在那儿;`release()` 之后回真记录。 */
function renderStudio(kind: string, record: Record<string, unknown>) {
  let release: () => void = () => {};
  const gate = new Promise<void>((resolve) => {
    release = resolve;
  });
  globalThis.fetch = vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input);
    const json = (body: unknown) => new Response(JSON.stringify(body), { status: 200, headers: { "content-type": "application/json" } });
    if (url.includes("/api/generation/sessions")) {
      return json([{ id: "s1", workspace_id: "w1", title: "会话", kind, provider_profile_id: null, model: "", is_mine: true,
                     shared: false, created_at: "2026-10-08T00:00:00Z", updated_at: "2026-10-08T00:00:00Z" }]);
    }
    if (url.includes("/api/generation/jobs")) {
      await gate;
      return json([{ ...RECORD, kind, ...record }]);
    }
    if (/\/api\/assets\/a1$/.test(url)) {
      return json({ id: "a1", name: "x", kind: "audio", media_info: { dialogue: [{ speaker: "v", text: "大家好" }] } });
    }
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
  return { release: () => act(() => release()) };
}

/** 骨架那一轮和真的那一轮,同一个位置上的几层。 */
function shells(article: Element) {
  const [promptRow, resultRow] = Array.from(article.children);
  return {
    article: article.className,
    promptRow: promptRow.className,
    bubble: promptRow.firstElementChild!.className,
    resultRow: resultRow.className,
    footnoteRow: resultRow.querySelector("small")!.parentElement!.className,
    footnote: resultRow.querySelector("small")!.className,
  };
}

describe("创作页:骨架按会话的种类画,外壳和真的那一轮同一套", () => {
  it.each([
    ["image", "[data-skeleton-frame='image']"],
    ["video", "[data-skeleton-frame='video']"],
    ["speech", "ul[aria-hidden] li"],
    ["podcast", "[data-podcast-dialogue-skeleton]"],
    ["audio", "ul[aria-hidden] li"],
  ])("%s", async (kind, frame) => {
    const { release } = renderStudio(kind, {});
    const skeletons = await waitFor(() => {
      const found = document.querySelectorAll(`[data-generation-skeleton='${kind}']`);
      expect(found.length).toBe(1);
      return found;
    });
    expect(skeletons[0].querySelector(frame)).toBeTruthy();
    //: 不是那块 320 的方块加一条 16px 高的细胶囊
    expect(document.querySelector(".max-w-\\[320px\\]")).toBeNull();
    const before = shells(skeletons[0]);
    const skeletonVideo = skeletons[0].querySelector("[data-skeleton-frame='video']")?.className;
    const skeletonTrack = skeletons[0].querySelector("ul[aria-hidden] li")?.className;

    await release();
    const real = await waitFor(() => {
      const found = document.querySelector("article[data-generation-status]");
      expect(found).toBeTruthy();
      return found!;
    });
    expect(document.querySelector("[data-generation-skeleton]")).toBeNull();
    expect(shells(real)).toEqual(before);
    if (kind === "video") {
      expect(real.querySelector("[data-generated-video]")!.className).toBe(skeletonVideo);
    }
    if (kind === "speech" || kind === "audio" || kind === "podcast") {
      expect(real.querySelector("[data-audio-track]")!.className).toBe(skeletonTrack);
    }
    if (kind === "image") {
      const img = real.querySelector("img")!;
      for (const cls of ["block", "rounded-lg", "border", "border-border"]) expect(img.className.split(" ")).toContain(cls);
      expect(img.className).toContain("max-h-[360px]");
      const frameBox = skeletons[0].querySelector("[data-skeleton-frame='image']")!;
      for (const cls of ["block", "rounded-lg", "border", "border-border"]) expect(frameBox.className.split(" ")).toContain(cls);
      //: 缩略图的宽(320)
      expect(frameBox.firstElementChild!.className).toContain("w-[320px]");
    }
  });

  it("播客:对谈稿那一行,素材到之前占着和骨架同一个壳", async () => {
    const { release } = renderStudio("podcast", {});
    await waitFor(() => expect(document.querySelector("[data-podcast-dialogue-skeleton]")).toBeTruthy());
    const skeletonRow = document.querySelector("[data-podcast-dialogue-skeleton]")!.className;
    await release();
    await waitFor(() => expect(document.querySelector("[data-podcast-dialogue]")).toBeTruthy());
    expect(document.querySelector("[data-podcast-dialogue]")!.className).toBe(skeletonRow);
  });
});

describe("对话:骨架用真气泡的外壳", () => {
  it("用户气泡那一列、药丸、助手那一轮,类名和真气泡一字不差", () => {
    const client = new QueryClient();
    const user = { id: "m1", role: "user", content: "帮我剪一段", payload: null, created_at: "2026-10-08T00:00:00Z" };
    const assistant = { id: "m2", role: "assistant", content: "好的", payload: { timeline: [{ type: "text", text: "好的" }] },
                        created_at: "2026-10-08T00:00:01Z" };
    const { container } = render(
      <QueryClientProvider client={client}>
        <div data-real="">
          <ChatBubble message={user as never} usageEvents={[]} workspaceId="w1" />
          <ChatBubble message={assistant as never} usageEvents={[]} workspaceId="w1" />
        </div>
        <div data-skeleton="">
          <ChatTranscriptSkeleton />
        </div>
      </QueryClientProvider>,
    );
    const [realUser, realAssistant] = Array.from(container.querySelector("[data-real]")!.children);
    const skeletonUser = container.querySelector("[data-skeleton-bubble='user']")!;
    const skeletonAssistant = container.querySelector("[data-skeleton-bubble='assistant']")!;
    //: 真气泡外层多一个 `group/bubble`(悬停脚注显形用的组名,不占版面)
    const layout = (element: Element) => element.className.replace("group/bubble", "").trim();
    expect(layout(skeletonUser)).toBe(layout(realUser));
    expect(skeletonUser.firstElementChild!.className).toBe(realUser.firstElementChild!.className);
    expect(layout(skeletonAssistant)).toBe(layout(realAssistant));
    //: 一轮回答里那一列(块与块的间距)也是同一个
    expect(skeletonAssistant.firstElementChild!.className).toBe(realAssistant.firstElementChild!.className);
    //: 脚注那一行(悬停才显形,但占高度)骨架也留着,同一个外框
    expect(skeletonUser.lastElementChild!.className.split(" ")).toEqual(
      expect.arrayContaining(realUser.lastElementChild!.className.split(" ").filter((cls) => !cls.includes("opacity") && !cls.includes("transition") && !cls.includes("duration") && cls !== "justify-end")),
    );
    expect(screen.queryAllByText("chatLoadingSession")).toHaveLength(0);
  });

  it("输入框下面那一行体征:读到之前占着同一个外框(不然消息一到它冒出来,输入框往上跳一行)", () => {
    const messages = [
      { id: "m1", role: "user", content: "帮我剪一段", payload: null, created_at: "2026-10-08T00:00:00Z" },
      { id: "m2", role: "assistant", content: "好的", payload: { timeline: [{ type: "text", text: "好的" }] }, created_at: "2026-10-08T00:00:01Z" },
    ];
    const { container, rerender } = render(<TraceStatsBar turns={[]} usageEvents={[]} pending className="px-3" />);
    const skeleton = container.firstElementChild!;
    expect(skeleton.hasAttribute("data-trace-stats-skeleton")).toBe(true);
    expect(skeleton.getAttribute("aria-hidden")).toBe("true");
    rerender(<TraceStatsBar turns={buildTurns(messages as never)} usageEvents={[]} className="px-3" />);
    const real = container.firstElementChild!;
    expect(real.hasAttribute("data-trace-stats-skeleton")).toBe(false);
    expect(real.className).toBe(skeleton.className);
  });
});
