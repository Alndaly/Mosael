/** @vitest-environment jsdom */

/**
 * AI Studio 左边那一列「对话记录」在**还没读回来**的时候,此前看着和「一条都没有」一模一样:
 * 一个空格子,上面还先闪出一排「素材调研 0 / 素材生成 0」的分组(维护者报的就是这个)。
 *
 * 「还没读到」和「确实没有」是两回事,这里把两边的样子钉住:
 * 加载中铺**贴着真行版式**的骨架(不摆空态那两句、不摆任何「某某 0」),确实没有才是空态,
 * 搜索之后没有结果又是第三条路(不铺骨架),读回来了骨架收掉、真行出现 —— 两个调用方(对话、创作)都接上了。
 */

import React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeAll, beforeEach, describe, expect, it, vi } from "vitest";

const TEXT: Record<string, string> = {
  chatNoSessions: "还没有对话,在右边说第一句话就开一段。",
  chatSessionsLoading: "读取对话…",
  chatSearchSessions: "搜索对话…",
  chatSearchNoMatch: "没有匹配的对话",
  generationNoSessions: "还没有创作会话",
  generationSessionsLoading: "读取创作会话…",
  generationSearchSessions: "搜索创作会话…",
  generationSearchNoMatch: "没有匹配的创作会话",
};

vi.mock("@/app/preferences", () => ({
  useI18n: () => (key: string) => TEXT[key] ?? key,
  usePreferences: () => ({ locale: "zh-CN" }),
}));

import { AiStudio } from "@/features/ai-studio/AiStudio";
import { ImagePreviewProvider } from "@/components/app/image-preview";
import { SessionList, type ListedSession, type SessionRowExtras } from "@/features/ai-studio/SessionList";

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
});

const originalFetch = globalThis.fetch;
afterEach(() => {
  globalThis.fetch = originalFetch;
  vi.unstubAllGlobals();
});
beforeEach(() => localStorage.clear());

const json = (body: unknown) =>
  new Response(JSON.stringify(body), { status: 200, headers: { "content-type": "application/json" } });

const GROUP = { id: "g1", workspace_id: "w1", kind: "agent", name: "素材调研", created_at: "2026-10-08T00:00:00Z" };

function row(id: string, title: string, groupId: string | null = null): ListedSession {
  return { id, title, group_id: groupId, is_mine: true, shared: false };
}

/** 分组那一路照旧走真的(它自己有查询),会话那一路由调用方当 prop 给进来。 */
function mockGroups(groups: unknown[] = []) {
  globalThis.fetch = vi.fn(async (input: RequestInfo | URL) =>
    String(input).includes("/api/session-groups") ? json(groups) : json([])) as never;
}

type ListProps = {
  sessions?: ListedSession[];
  loading?: boolean;
  loaded?: boolean;
  groups?: unknown[];
  extras?: (session: ListedSession) => SessionRowExtras | null;
};

/** 同一个容器里换 props(不是重新挂一个)—— 加载态和读到的样子才比得出来。 */
function renderList(initial: ListProps = {}) {
  mockGroups(initial.groups ?? []);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const view = (props: ListProps) => (
    <QueryClientProvider client={client}>
      <SessionList
        kind="agent"
        workspaceId="w1"
        sessions={props.sessions ?? []}
        loading={props.loading ?? false}
        loaded={props.loaded ?? true}
        activeSessionId={null}
        onSelect={() => {}}
        onCreate={() => {}}
        creating={false}
        onDeleted={() => {}}
        extras={props.extras}
      />
    </QueryClientProvider>
  );
  const utils = render(view(initial));
  return { ...utils, show: (props: ListProps) => utils.rerender(view(props)) };
}

const skeleton = () => document.querySelector<HTMLElement>("[data-session-skeleton]");

describe("加载中:铺骨架,不摆空态、不摆「某某 0」", () => {
  it("骨架出现,空态那两句和任何「0」都不出现;骨架本身不给读屏念一屏假行", async () => {
    //: 先把分组那一趟读完(读到之后这一组确实在列表上,计数是 0),再换成「会话还在读」 ——
    //: 于是「加载中不摆分组计数」这条真被考到:分组数据在手,Loading 时也不许摆出来。
    const { show } = renderList({ loaded: true, groups: [GROUP] });
    await waitFor(() => expect(document.querySelector("[data-group-toggle]")).toBeTruthy());

    show({ loading: true, loaded: false, groups: [GROUP] });

    const shape = skeleton();
    expect(shape, "还没读到就什么都不摆 = 看着像一条都没有").toBeTruthy();
    //: 读屏听到的是「正在读取对话…」这一个状态区,底下那些假行不念(既有约定见 AssetGridPicker 的 GridSkeleton)
    expect(shape!.getAttribute("role")).toBe("status");
    expect(shape!.getAttribute("aria-busy")).toBe("true");
    expect(shape!.textContent).toContain("读取对话…");

    //: 一屏放得下的几行,每行都不给读屏念
    const rows = shape!.querySelectorAll("[data-session-skeleton-row]");
    expect(rows.length).toBeGreaterThanOrEqual(5);
    expect(rows.length).toBeLessThanOrEqual(8);
    for (const r of rows) expect(r.getAttribute("aria-hidden")).toBe("true");

    //: 空态那两句只说「确实没有」;分组计数(那一排「某某 0」)加载中一个都不摆
    expect(screen.queryByText(TEXT.chatNoSessions)).toBeNull();
    expect(screen.queryByText("chatNoSessions")).toBeNull();
    expect(document.querySelector("[data-group-toggle]"), "「素材调研 0」不该先闪一下").toBeNull();
    expect(screen.queryByText("素材调研")).toBeNull();
    expect(screen.queryByText("0")).toBeNull();
  });

  it("骨架贴着真行的版式:同一圈内边距、同一个两行文字那一列、分组标题同一套排版", async () => {
    const { show } = renderList({ loading: true, loaded: false, groups: [GROUP] });
    const skeletonRow = skeleton()!.querySelector("[data-session-skeleton-row]") as HTMLElement;
    const skeletonGroup = skeleton()!.querySelector("[data-session-skeleton-group]") as HTMLElement;
    expect(skeletonRow).toBeTruthy();
    expect(skeletonGroup).toBeTruthy();

    //: 真行(读到了之后的这一条):去掉「能点 / 能悬停 / 拖影」那几样,剩下的壳就是骨架行的壳。
    //: 比的是**同一套类**(排一下序:twMerge 会把两边都有的 `w-full` 并成一个,落在后出现的位置)。
    show({
      sessions: [row("s1", "海边的灯塔")],
      loaded: true,
      groups: [GROUP],
      extras: () => ({ subtitle: "在剪辑《A》里开的" }),
    });
    const real = await screen.findByRole("button", { name: /海边的灯塔/ });
    const CHROME = new Set(["cursor-pointer", "rounded-md", "transition-colors", "duration-100", "hover:bg-muted"]);
    const shell = (el: Element) => el.className.split(" ").filter((cls) => !CHROME.has(cls)).sort();
    expect(shell(real)).toEqual(shell(skeletonRow));

    //: 标题 14px、副标题 12px 那两行:骨架按同两种字号占位,加载完行高不跳
    for (const size of ["text-ui-sm", "text-ui-xs"]) {
      expect(skeletonRow.querySelector(`.${size}`), `骨架缺 ${size} 那一行`).toBeTruthy();
      expect(real.querySelector(`.${size}`), `真行缺 ${size} 那一行`).toBeTruthy();
    }
    //: 骨架里那两行字都占着一行字那么高(SkeletonLine:高度按它那一层的行高算)
    expect(skeletonRow.querySelectorAll('[data-slot="skeleton-line"]').length).toBe(2);

    //: 分组标题:骨架那一块和真 GroupToggle 的排版是同一套类,改一头不改另一头就对不上
    const toggle = await waitFor(() => {
      const found = document.querySelector("[data-group-toggle]");
      expect(found, "分组那一趟还没读完").toBeTruthy();
      return found as HTMLElement;
    });
    for (const cls of ["flex", "w-full", "items-center", "gap-1", "px-1.5", "py-1", "text-ui-xs", "text-left"]) {
      expect(skeletonGroup.className.split(" "), `骨架分组标题缺 ${cls}`).toContain(cls);
      expect(toggle.className.split(" "), `真分组标题缺 ${cls}`).toContain(cls);
    }
  });

  it("分组计数只在真有数据时摆:加载中连「1」都没有,读到了才出现", async () => {
    const { show } = renderList({ loading: true, loaded: false, groups: [GROUP] });
    expect(screen.queryByText("1")).toBeNull();

    show({ sessions: [row("s2", "素材调研", "g1")], loaded: true, groups: [GROUP] });
    const toggle = await waitFor(() => {
      const found = document.querySelector("[data-group-toggle]");
      expect(found).toBeTruthy();
      return found as HTMLElement;
    });
    expect(toggle.textContent).toContain("1");
    expect(skeleton()).toBeNull();
  });
});

describe("三种「空」分开:加载中 vs 确实没有 vs 搜索之后没有结果", () => {
  it("确实没有(非加载):空态那一句出来,骨架不出现", async () => {
    renderList({ loaded: true, sessions: [] });
    expect(await screen.findByText(TEXT.chatNoSessions)).toBeTruthy();
    expect(skeleton()).toBeNull();
  });

  it("搜索之后没有结果(非加载):走「没有匹配」那一条,不铺骨架", async () => {
    renderList({ loaded: true, sessions: [row("s1", "海边的灯塔"), row("s2", "素材调研")] });

    const input = await screen.findByPlaceholderText(TEXT.chatSearchSessions);
    fireEvent.change(input, { target: { value: "zzz" } });

    expect(await screen.findByText(TEXT.chatSearchNoMatch)).toBeTruthy();
    expect(screen.queryByText(TEXT.chatNoSessions)).toBeNull();
    expect(skeleton(), "搜不到不是「还在读」,不该铺骨架").toBeNull();
  });

  it("搜到了:真行还在,骨架和两条空态都不出现", async () => {
    renderList({ loaded: true, sessions: [row("s1", "海边的灯塔"), row("s2", "素材调研")] });

    const input = await screen.findByPlaceholderText(TEXT.chatSearchSessions);
    fireEvent.change(input, { target: { value: "灯塔" } });

    expect(screen.getByRole("button", { name: /海边的灯塔/ })).toBeTruthy();
    expect(screen.queryByText(TEXT.chatSearchNoMatch)).toBeNull();
    expect(skeleton()).toBeNull();
  });
});

describe("两个调用方都接上了:加载中不再看着像一条都没有", () => {
  /** 会话那一趟挂着不回:骨架在那儿;`release()` 之后回真会话。 */
  function renderStudio(tab: "create" | "chat") {
    let release: () => void = () => {};
    const gate = new Promise<void>((resolve) => {
      release = resolve;
    });
    const at = "2026-10-08T00:00:00Z";
    globalThis.fetch = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.includes("/api/generation/sessions")) {
        await gate;
        return json([
          {
            id: "s1", workspace_id: "w1", title: "海边的灯塔", kind: "image", provider_profile_id: null, model: "",
            origin_kind: "studio", origin_id: "", origin_name: "", origin_state: "ok", is_mine: true, shared: false,
            created_at: at, updated_at: at,
          },
        ]);
      }
      if (url.includes("/api/agent/sessions")) {
        await gate;
        return json([
          {
            id: "a1", workspace_id: "w1", title: "整理素材库", is_mine: true, shared: false,
            home_kind: "studio", home_id: "", home_name: "", home_state: "ok", created_at: at, updated_at: at,
          },
        ]);
      }
      return json([]);
    }) as never;
    localStorage.setItem("mosael:tab:ai-studio", tab);
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

  it.each([
    ["创作", "create", "读取创作会话…", "还没有创作会话", "海边的灯塔"],
    ["对话", "chat", "读取对话…", "还没有对话,在右边说第一句话就开一段。", "整理素材库"],
  ] as const)("%s:读回来了骨架收掉、真行出现", async (_name, tab, loadingLabel, emptyText, title) => {
    const { release } = renderStudio(tab);

    //: 还没读回来:骨架在,空态那句不在,分组计数也不在
    const shape = await waitFor(() => {
      const found = skeleton();
      expect(found).toBeTruthy();
      return found!;
    });
    expect(shape.textContent).toContain(loadingLabel);
    expect(screen.queryByText(emptyText)).toBeNull();
    expect(document.querySelector("[data-group-toggle]")).toBeNull();

    await release();

    expect(await screen.findByRole("button", { name: new RegExp(title) })).toBeTruthy();
    await waitFor(() => expect(skeleton()).toBeNull());
    expect(screen.queryByText(emptyText)).toBeNull();
  });
});
