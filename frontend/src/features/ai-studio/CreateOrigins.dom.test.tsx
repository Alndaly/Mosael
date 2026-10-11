/** @vitest-environment jsdom */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import React from "react";
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

/**
 * 创作会话记出处(ADR 0052,D41–D47):
 *
 * - 列表上面是在这里开的(创作页、「以前的语音 / 播客」);画板、工作流、智能体……开出来的收进最下面「来自别处」,默认合着、带个数;
 * - 别处开的标题空着,写那一处现在叫什么(删了写「已删除的创意画板」);迁移之前的老会话有自己的标题,那一处写在副标题上;
 * - 那一处还在就有「回到那里」;删了、看不见的没有;
 * - 一条会话先取最近的一页,有更早的就摆一颗「显示更早的」,点了多要一页。
 */

const TEXT: Record<string, string> = {
  createOriginBoard: "画板《{name}》",
  createOriginDeletedBoard: "已删除的画板",
  createOriginAgent: "对话《{name}》",
  createOriginEarlierSpeech: "以前的语音",
};
vi.mock("@/app/preferences", () => ({
  useI18n: () => (key: string) => TEXT[key] ?? key,
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
});
beforeEach(() => {
  localStorage.clear();
  localStorage.setItem("mosael:tab:ai-studio", "create");
});

function row(id: string, title: string, origin: Record<string, string> = {}, at = "2026-10-08T00:00:00Z") {
  return {
    id, workspace_id: "w1", title, kind: "image", provider_profile_id: null, model: "", is_mine: true, shared: false,
    origin_kind: "studio", origin_id: "", origin_name: "", origin_state: "ok", ...origin, created_at: at, updated_at: at,
  };
}

const SESSIONS = [
  row("s-mine", "海边的灯塔"),
  row("s-earlier", "", { origin_kind: "audio_page", origin_id: "speech" }),
  row("s-board", "", { origin_kind: "board", origin_id: "b1", origin_name: "镜头与灵感" }),
  row("s-gone", "清晨的林间草地", { origin_kind: "board", origin_id: "", origin_state: "deleted" }),
  row("s-chat", "", { origin_kind: "agent", origin_id: "a1", origin_name: "整理素材库" }),
];

function record(index: number) {
  return {
    id: `g${index}`, workspace_id: "w1", session_id: "s-board", job_id: null, provider_profile_id: null, provider: "p",
    model: "m", kind: "image", request: { prompt: `第 ${index} 次` }, result_asset_id: null, result_asset_ids: [],
    error: null, error_summary: null, stopped: true, retrievable: false, costs: [], cost_confidence: null,
    created_at: "2026-10-08T00:00:00Z", updated_at: "2026-10-08T00:00:00Z",
  };
}

function renderStudio(records: (limit: number) => unknown[] = () => []) {
  const gets: string[] = [];
  globalThis.fetch = vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input);
    gets.push(url);
    const json = (body: unknown) => new Response(JSON.stringify(body), { status: 200, headers: { "content-type": "application/json" } });
    if (url.includes("/api/generation/sessions")) return json(SESSIONS);
    if (url.includes("/api/generation/jobs")) {
      return json(records(Number(new URL(url, "http://x").searchParams.get("limit") ?? "0")));
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
  return { gets };
}

describe("创作会话的出处", () => {
  it("上面是在这里开的;别处来的收进「来自别处」,合着、带个数,展开看得见那一处的名字", async () => {
    renderStudio();
    expect(await screen.findByRole("button", { name: /海边的灯塔/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /以前的语音/ })).toBeInTheDocument();
    const aside = document.querySelector("[data-session-aside]")!;
    const toggle = within(aside as HTMLElement).getByRole("button", { name: /createFromElsewhere/ });
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    expect(toggle.textContent).toContain("3");
    expect(screen.queryByRole("button", { name: /画板《镜头与灵感》/ })).toBeNull();

    fireEvent.click(toggle);
    expect(toggle).toHaveAttribute("aria-expanded", "true");
    //: 标题空着的写那一处的名字;老会话有自己的标题,那一处(删了)写在副标题上
    const board = screen.getByRole("button", { name: /画板《镜头与灵感》/ });
    const gone = screen.getByRole("button", { name: /清晨的林间草地/ });
    expect(gone.closest("[data-session-row]")?.textContent ?? gone.parentElement!.parentElement!.textContent).toContain("已删除的画板");
    expect(screen.getByRole("button", { name: /对话《整理素材库》/ })).toBeInTheDocument();
    //: 那一处还在的有「回到那里」,删了的没有
    const goBacks = screen.getAllByRole("button", { name: "createGoToOrigin" });
    expect(goBacks).toHaveLength(2);
    expect(board).toBeInTheDocument();
  });

  it("搜索照旧搜全部:来自别处的命中了就展开着", async () => {
    renderStudio();
    await screen.findByRole("button", { name: /海边的灯塔/ });
    fireEvent.change(screen.getByRole("searchbox"), { target: { value: "镜头" } });
    expect(await screen.findByRole("button", { name: /画板《镜头与灵感》/ })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /海边的灯塔/ })).toBeNull();
  });

  it("打开别处的那条:标题栏写那一处;记录先取一页,有更早的就点「显示更早的」多要一页", async () => {
    localStorage.setItem("mosael.generation.session.w1.create", "s-board");
    const { gets } = renderStudio((limit) => Array.from({ length: Math.min(limit, 45) }, (_, index) => record(index)));
    await waitFor(() => expect(document.querySelectorAll("article[data-generation-status]").length).toBe(40));
    expect(screen.getAllByText("画板《镜头与灵感》").length).toBeGreaterThan(0);
    //: 开着的那条在「来自别处」里:那一摞展开着,看得见它在哪一行
    expect(document.querySelector("[data-session-aside] > button")).toHaveAttribute("aria-expanded", "true");
    expect(gets.some((url) => url.includes("session_id=s-board") && url.includes("limit=41"))).toBe(true);
    const earlier = screen.getByRole("button", { name: "createShowEarlier" });
    fireEvent.click(earlier);
    await waitFor(() => expect(document.querySelectorAll("article[data-generation-status]").length).toBe(45));
    expect(gets.some((url) => url.includes("limit=81"))).toBe(true);
    expect(screen.queryByRole("button", { name: "createShowEarlier" })).toBeNull();
  });

describe("选中那一行是整行,「回到那里」独立", () => {
  /**
   * 最下面那一摞「来自别处」(画板 / 工作流 / 对话开出来的都在里面)展开着。
   *
   * **只在合着时才点**:当前开着的那条会话就在这一摞里时,它本来就是展开的
   * (ADR 0052 §3)——照点一下反而把它合上,后面就找不到那一行了。
   */
  async function expand() {
    await screen.findByRole("button", { name: /海边的灯塔/ });
    const aside = document.querySelector("[data-session-aside]") as HTMLElement;
    const toggle = within(aside).getByRole("button", { name: /createFromElsewhere/ });
    if (toggle.getAttribute("aria-expanded") === "false") fireEvent.click(toggle);
    return screen.findByRole("button", { name: /画板《镜头与灵感》/ });
  }

  it("底色铺在整行上(连右侧「回到那里」一起),不是只在标题那一格", async () => {
    localStorage.setItem("mosael.generation.session.w1.create", "s-board");
    renderStudio();
    const title = await expand();
    //: 有那句副标题 / 那颗按钮时,「整行」是外面那一层(底色、左边那条竖条、拖影都在它身上)。
    const line = title.closest("[data-session-row]") as HTMLElement;
    expect(line, "整行那一层要认得出来(data-session-row)").toBeTruthy();
    expect(line.className, "选中底色在整行那一层上").toContain("color-mix(in_srgb,var(--primary)_9%");
    expect(line.className, "左边那条圆角竖条也在整行那一层上").toContain("before:bg-primary");
    //: 那颗「回到那里」在整行**里面** —— 底色盖住它,而不是把它落在外面。
    expect(line.contains(within(line).getByRole("button", { name: "createGoToOrigin" }))).toBe(true);
    //: 标题那颗按钮自己不再画一层底色(两处都画的话,右边那颗又落回"没盖住")。
    expect(title.className, "底色只画一层(在整行上)").not.toContain("color-mix(in_srgb,var(--primary)_9%");
  });

  it("点「回到那里」:走它自己那一条,不连带打开这一行", async () => {
    //: 当前开着的是「海边的灯塔」;去点**另一条**(画板那条)的「回到那里」——
    //: 若那一行也被点开了,当前会话会被换成 s-board,这条断言就红。
    localStorage.setItem("mosael.generation.session.w1.create", "s-mine");
    renderStudio();
    const title = await expand();
    const goBack = within(title.closest("[data-session-row]") as HTMLElement).getByRole("button", { name: "createGoToOrigin" });

    fireEvent.click(goBack);

    //: 它去那一处(画板),但没把这一条打开成当前会话 —— 两个是兄弟按钮,点击互不牵连。
    await waitFor(() => expect(localStorage.getItem("mosael.generation.session.w1.create")).toBe("s-mine"));
  });
});
});
