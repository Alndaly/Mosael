/** @vitest-environment jsdom */
/**
 * 字幕列表每一行的「翻译这一段」。
 *
 * 维护者要的是:每行一颗,点一下**只翻这一条**,而且**沿用「翻译」弹层里那一份设置**
 * (目标语言 / 引擎 / 保留原文),不另建一套默认;进行中那颗按钮转圈、能取消,
 * 失败要说清原因;顶部弹层原来的「仅选中的 N 条 / 全部」行为不变。
 *
 * 这里从按钮一路测到真的 `translateTexts` + 打桩的 `fetch`,而不是只测纯函数 ——
 * 「只送这一条」「沿用双语开关」都是**请求体里看得见**的事实。
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import React from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/app/preferences", () => ({
  useI18n: () => (key: string) => strings.templates[key] ?? key,
  usePreferences: () => ({ locale: "zh-CN" }),
}));

const strings = vi.hoisted(() => ({
  templates: {
    cancel: "取消",
    lang_en: "英语",
    lang_ja: "日语",
    subtitleTranslate: "翻译",
    subtitleTranslateTo: "目标语言",
    subtitleTranslateEngine: "翻译引擎",
    subtitleTranslateEngineDefault: "按默认",
    subtitleTranslateSelectedOnly: "仅选中的 {n} 条",
    subtitleTranslateBilingual: "保留原文(双语)",
    subtitleTranslateApply: "翻译全部 {n} 条",
    subtitleTranslateApplySelected: "翻译选中 {n} 条",
    subtitleTranslateProgress: "翻译中 {done}/{total}…",
    subtitleTranslateNote: "就地替换字幕文本,可撤销",
    subtitleTranslateDone: "已翻译 {n} 条字幕",
    subtitleTranslateFailed: "翻译失败",
    subtitleTranslatePartial: "前 {n} 条已写入轨道,其余保持原文。",
    subtitleTranslateCancelled: "已取消翻译",
    subtitleTranslateCancelledNone: "没有写入任何字幕。",
    subtitleTranslateTimedOut: "翻译超时",
    subtitleTranslateTimeout: "翻译服务在 {seconds} 秒内没有响应,已停止。",
    subtitleTranslateDeadline: "这次翻译超过 {minutes} 分钟还没完成,已停止。",
    subtitleTranslateUnreachable: "连不上翻译服务",
    subtitleTranslateThis: "翻译这一段",
    subtitleTranslateThisHint: "只翻这一条,沿用「翻译」弹层里的设置",
    subtitleTranslateThisCancel: "取消这一条的翻译",
    subtitleTranslateThisCancelHint: "正在翻这一条,点一下停下",
  } as Record<string, string>,
}));

const toastMock = vi.hoisted(() =>
  Object.assign(vi.fn(), { error: vi.fn(), success: vi.fn(), message: vi.fn() }),
);
vi.mock("sonner", () => ({ toast: toastMock }));

vi.stubGlobal("ResizeObserver", class {
  observe() {}
  unobserve() {}
  disconnect() {}
});

import { SubtitlePanel } from "@/features/editor/SubtitlePanel";
import { useEditorStore } from "@/features/editor/editorStore";

const fetchMock = vi.fn();
type Pending = { body: { texts: string[]; target_lang: string; engine: string }; init: RequestInit; resolve: (response: Response) => void };
let pending: Pending[] = [];

function jsonResponse(payload: unknown): Response {
  return new Response(JSON.stringify(payload), {
    status: 200,
    headers: { "content-type": "application/json" },
  });
}

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
          timeline_start: index * 2,
          src_in: 0,
          src_out: 1,
          speed: 1,
          text_override: text,
        })),
      },
    ],
  } as never;
}

function renderPanel(texts: string[], onApplyTexts = vi.fn(async () => undefined)) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <SubtitlePanel
        sequence={sequenceWith(texts)}
        onSetText={vi.fn()}
        onAddSubtitle={vi.fn()}
        onDeleteClip={vi.fn()}
        onApplyTexts={onApplyTexts}
      />
    </QueryClientProvider>,
  );
  return { onApplyTexts };
}

/** 把当前挂起的那一批按「每条前面加 T:」回掉。 */
async function resolveBatch(index: number) {
  const call = pending[index];
  await act(async () => {
    call.resolve(jsonResponse({ translations: call.body.texts.map((text) => `T:${text}`) }));
  });
}

/** 行内的「翻译这一段」按钮,按行序。 */
function rowTranslateButtons() {
  return screen.getAllByRole("button", { name: "翻译这一段" });
}

beforeEach(() => {
  pending = [];
  fetchMock.mockReset();
  vi.stubGlobal("fetch", fetchMock);
  useEditorStore.setState({ selectedClipIds: [] });
  toastMock.mockClear();
  toastMock.error.mockClear();
  toastMock.success.mockClear();
  toastMock.message.mockClear();
  fetchMock.mockImplementation((input: RequestInfo | URL, init?: RequestInit) => {
    if (String(input).includes("/api/settings/capabilities")) return Promise.resolve(jsonResponse([]));
    const body = JSON.parse(String(init?.body)) as Pending["body"];
    return new Promise<Response>((resolve, reject) => {
      const signal = init?.signal;
      signal?.addEventListener("abort", () => reject(new DOMException("Aborted", "AbortError")), { once: true });
      pending.push({ body, init: init ?? {}, resolve });
    });
  });
});

describe("行内「翻译这一段」· 按钮", () => {
  it("每一行都有一颗,名字和悬停说明都在;点它不会顺手改时间线上的选中", async () => {
    const user = userEvent.setup();
    renderPanel(["第一条", "第二条", "第三条"]);

    const buttons = rowTranslateButtons();
    expect(buttons).toHaveLength(3);
    for (const button of buttons) expect(button).toHaveAttribute("aria-label", "翻译这一段");
    //: 名字只写一次(IconButton 的 label),悬停说明里看得到它和「只翻这一条」那句补充。
    await user.hover(buttons[0]);
    const tip = await screen.findByRole("tooltip", {}, { timeout: 3000 });
    expect(tip).toHaveTextContent("翻译这一段");
    expect(tip).toHaveTextContent("只翻这一条");
    //: 行内翻译只动这一条,**不借用时间线上的选中**(选中是全局的)。
    await user.click(buttons[1]);
    await waitFor(() => expect(pending.length).toBe(1));
    expect(useEditorStore.getState().selectedClipIds).toEqual([]);
    //: 收尾:让这一趟跑完,别把挂起的请求留在测试之间。
    await resolveBatch(0);
  });
});

describe("行内「翻译这一段」· 只翻这一条", () => {
  it("点第 2 行:送去的只有那一条原文,落回去的也只有它", async () => {
    const user = userEvent.setup();
    const { onApplyTexts } = renderPanel(["第一条", "第二条", "第三条"]);

    await user.click(rowTranslateButtons()[1]);
    await waitFor(() => expect(pending.length).toBe(1));
    expect(pending[0].body.texts).toEqual(["第二条"]);
    expect(pending[0].body.texts).not.toEqual(["第一条", "第二条", "第三条"]);

    await resolveBatch(0);
    await waitFor(() => expect(onApplyTexts).toHaveBeenCalledTimes(1));
    expect(onApplyTexts).toHaveBeenCalledWith([{ clip_id: "c1", text: "T:第二条" }]);
  });
});

describe("行内「翻译这一段」· 沿用弹层设置", () => {
  it("弹层里改成日语 + 打开双语,行内翻译就带日语、原文在上;关掉双语后不再带原文", async () => {
    const user = userEvent.setup();
    const { onApplyTexts } = renderPanel(["第一条", "第二条", "第三条"]);

    // 打开顶部「翻译」弹层:改目标语言(默认 en → ja),打开「保留原文」。
    await user.click(await screen.findByRole("button", { name: "翻译" }));
    const [language] = screen.getAllByRole("combobox");
    await user.click(language);
    await user.click(await screen.findByRole("option", { name: "日语" }));
    await user.click(screen.getByRole("switch"));
    expect(screen.getByRole("switch")).toBeChecked();

    // 点第 1 行的行内翻译:请求体用的是弹层里刚选的语言(共享同一份状态)。
    await user.click(rowTranslateButtons()[0]);
    await waitFor(() => expect(pending.length).toBe(1));
    expect(pending[0].body.target_lang).toBe("ja");
    expect(pending[0].body.texts).toEqual(["第一条"]);

    await resolveBatch(0);
    await waitFor(() => expect(onApplyTexts).toHaveBeenCalledTimes(1));
    //: 「保留原文」照旧生效:原文在上、译文在下。
    expect(onApplyTexts).toHaveBeenCalledWith([{ clip_id: "c0", text: "第一条\nT:第一条" }]);

    // 回到弹层关掉双语,再翻下一条:只落译文。
    await user.click(await screen.findByRole("button", { name: "翻译" }));
    await user.click(screen.getByRole("switch"));
    expect(screen.getByRole("switch")).not.toBeChecked();

    await user.click(rowTranslateButtons()[1]);
    await waitFor(() => expect(pending.length).toBe(2));
    expect(pending[1].body.target_lang).toBe("ja");
    await resolveBatch(1);
    await waitFor(() => expect(onApplyTexts).toHaveBeenCalledTimes(2));
    expect(onApplyTexts).toHaveBeenLastCalledWith([{ clip_id: "c1", text: "T:第二条" }]);
  });
});

describe("行内「翻译这一段」· 进行中与失败", () => {
  it("进行中那颗按钮转圈、再点一下就取消这一条,并说已取消", async () => {
    const user = userEvent.setup();
    const { onApplyTexts } = renderPanel(["第一条", "第二条"]);

    await user.click(rowTranslateButtons()[0]);
    await waitFor(() => expect(pending.length).toBe(1));

    // 同一颗按钮(还在原位),只是名字和图标换成了「取消」+ 转圈。
    const busy = screen.getByRole("button", { name: "取消这一条的翻译" });
    expect(busy).toHaveAttribute("aria-busy", "true");
    expect(busy.querySelector(".animate-mosael-spin")).not.toBeNull();

    await user.click(busy);
    await waitFor(() =>
      expect(toastMock.message).toHaveBeenCalledWith("已取消翻译", {
        description: "没有写入任何字幕。",
      }),
    );
    expect(pending[0].init.signal?.aborted).toBe(true);
    expect(onApplyTexts).not.toHaveBeenCalled();
    //: 取消之后不再发下一批。
    expect(pending).toHaveLength(1);
    await waitFor(() => expect(rowTranslateButtons()).toHaveLength(2));
    expect(rowTranslateButtons()[0]).toHaveAttribute("aria-busy", "false");
  });

  it("失败时说清原因(复用现有的「连不上翻译服务」),不静默", async () => {
    fetchMock.mockImplementation((input: RequestInfo | URL) => {
      if (String(input).includes("/api/settings/capabilities")) return Promise.resolve(jsonResponse([]));
      return Promise.reject(new TypeError("Failed to fetch"));
    });
    const user = userEvent.setup();
    const { onApplyTexts } = renderPanel(["第一条", "第二条"]);

    await user.click(rowTranslateButtons()[0]);
    await waitFor(() =>
      expect(toastMock.error).toHaveBeenCalledWith("连不上翻译服务", expect.anything()),
    );
    expect(onApplyTexts).not.toHaveBeenCalled();
    await waitFor(() => expect(rowTranslateButtons()).toHaveLength(2));
    expect(rowTranslateButtons()[0]).toHaveAttribute("aria-busy", "false");
  });
});

describe("顶部弹层的「仅选中 / 全部」不变", () => {
  it("有选中时默认只翻选中;关掉「仅选中的 N 条」后翻全部", async () => {
    const user = userEvent.setup();
    useEditorStore.setState({ selectedClipIds: ["c2"] });
    const { onApplyTexts } = renderPanel(["第一条", "第二条", "第三条"]);

    await user.click(await screen.findByRole("button", { name: "翻译" }));
    await user.click(await screen.findByRole("button", { name: "翻译选中 1 条" }));
    await waitFor(() => expect(pending.length).toBe(1));
    expect(pending[0].body.texts).toEqual(["第三条"]);
    await resolveBatch(0);
    await waitFor(() => expect(onApplyTexts).toHaveBeenCalledTimes(1));

    await user.click(await screen.findByRole("button", { name: "翻译" }));
    expect(screen.getByText("仅选中的 1 条")).toBeInTheDocument();
    //: 选中开关排在双语开关前面。
    await user.click(screen.getAllByRole("switch")[0]);
    await user.click(await screen.findByRole("button", { name: "翻译全部 3 条" }));
    await waitFor(() => expect(pending.length).toBe(2));
    expect(pending[1].body.texts).toEqual(["第一条", "第二条", "第三条"]);
  });
});
