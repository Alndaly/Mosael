/** @vitest-environment jsdom */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import React from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { readHint } from "@/test/hint";

/**
 * 逐字稿列表读起来要像一段**文稿**,而不是一列带前缀的行。
 *
 * 用户给的截图里,两句话前面各挂着一个一模一样的 `[说话人 00]` —— 单人口播是最常见的输入,
 * 而那个标签在每一行重复同一件事:把正文往右顶,还抢走第一眼。分得出两个人时它才是信息。
 */

vi.mock("@/app/preferences", () => ({
  useI18n: () => (key: string) => (key === "transcriptSpeakerLabel" ? "说话人 {n}" : key),
  usePreferences: () => ({ locale: "zh-CN" }),
}));

import { TranscriptPanel } from "@/features/editor/TranscriptPanel";

// jsdom 没有实现它,而面板会把当前句滚进视野。
Element.prototype.scrollIntoView = vi.fn();

const originalFetch = globalThis.fetch;
afterEach(() => {
  globalThis.fetch = originalFetch;
});

function sequenceWith(clipId: string) {
  return {
    id: "s1",
    workspace_id: "w1",
    revision: 1,
    tracks: [
      {
        id: "t1",
        kind: "video",
        clips: [
          {
            id: clipId,
            asset_id: "a1",
            asset_kind: "video",
            timeline_start: 0,
            src_in: 0,
            src_out: 60,
          },
        ],
      },
    ],
  } as never;
}

function serveTranscript(speakers: Array<string | null>) {
  const transcript = {
    id: "tr1",
    language: "zh",
    segments: speakers.map((speaker, index) => ({
      id: `seg${index}`,
      start_time: index * 10,
      end_time: index * 10 + 5,
      text: `第${index}句`,
      speaker,
      tokens: [{ start_time: index * 10, end_time: index * 10 + 5, text: `第${index}句` }],
    })),
  };
  globalThis.fetch = vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input);
    const body = url.includes("/transcript") ? transcript : [];
    return new Response(JSON.stringify(body), {
      status: 200,
      headers: { "content-type": "application/json" },
    });
  }) as never;
}

function renderPanel() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <TranscriptPanel sequence={sequenceWith("c1")} onCutSegment={vi.fn()} />
    </QueryClientProvider>,
  );
}

describe("打开剪辑页时 React 不报错", () => {
  //: 此前 segmentsByAsset 的依赖写成 `[assetIds, ...每条逐字稿的 data]`:素材从 0 条变成 N 条时依赖数组跟着变长,
  //: React 每次打开剪辑页都在控制台报「The final argument passed to useMemo changed size between renders」。
  it("片段从没有到有:依赖数组是定长的", async () => {
    serveTranscript(["SPEAKER_00"]);
    const errors = vi.spyOn(console, "error").mockImplementation(() => undefined);
    try {
      const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
      const empty = { id: "s1", workspace_id: "w1", revision: 1, tracks: [{ id: "t1", kind: "video", clips: [] }] } as never;
      const view = render(
        <QueryClientProvider client={client}>
          <TranscriptPanel sequence={empty} onCutSegment={vi.fn()} />
        </QueryClientProvider>,
      );
      view.rerender(
        <QueryClientProvider client={client}>
          <TranscriptPanel sequence={sequenceWith("c1")} onCutSegment={vi.fn()} />
        </QueryClientProvider>,
      );
      await screen.findByText("第0句");
      const sized = errors.mock.calls.map((call) => String(call[0])).filter((message) => message.includes("changed size between renders"));
      expect(sized).toEqual([]);
    } finally {
      errors.mockRestore();
    }
  });
});

describe("逐字稿列表", () => {
  it("只有一个说话人时不挂说话人标签 —— 每行都一样的东西不是信息", async () => {
    serveTranscript(["SPEAKER_00", "SPEAKER_00"]);
    renderPanel();

    await screen.findByText("第0句");
    expect(screen.queryByRole("img", { name: "说话人 1" })).toBeNull();
  });

  it("分得出两个人时才挂,而且时间码、说话人、正文在同一横向栅格里", async () => {
    serveTranscript(["SPEAKER_00", "SPEAKER_01"]);
    const { container } = renderPanel();

    const sentenceText = await screen.findByText("第0句");
    await waitFor(() => expect(screen.getByRole("img", { name: "说话人 1" })).toBeInTheDocument());
    const speaker = screen.getByRole("img", { name: "说话人 1" });
    expect(screen.getByRole("img", { name: "说话人 2" })).toBeInTheDocument();
    // 栏里放得下的是人形图标 + 序号,完整名字在悬停说明 / aria-label 上。
    // 此前是一个光秃秃的 `00` 挨着时间码 `00:00.0` —— 用户问"这个绿色的 00 是什么"。
    expect(speaker.textContent).toBe("1");
    expect(speaker.querySelector("svg")).not.toBeNull();
    expect(speaker).toHaveAttribute("aria-label", "说话人 1");

    const row = container.querySelector(".group\\/sentence");
    expect(row?.className).toContain("grid-cols-[92px_minmax(0,1fr)]");
    // 时间码和说话人同在顶部元数据组里；正文是相邻的栅格列。
    expect(speaker.parentElement?.className).toContain("h-6");
    expect(speaker.parentElement?.className).toContain("items-center");
    expect(speaker.parentElement?.parentElement).toBe(row);
    expect(sentenceText.parentElement?.parentElement).toBe(row);
  });

  it("句子和时间码在同一套栅格里 —— 对齐是结构给的,不是手调的边距", async () => {
    serveTranscript(["SPEAKER_00"]);
    const { container } = renderPanel();

    await screen.findByText("第0句");
    const row = container.querySelector(".group\\/sentence");
    expect(row?.className).toContain("grid-cols-[58px_minmax(0,1fr)]");
    expect(row?.className).not.toContain("ml-[46px]");
  });

  it("正文过长时自然换行而不是截断", async () => {
    serveTranscript(["SPEAKER_00"]);
    const { container } = renderPanel();

    await screen.findByText("第0句");
    const body = container.querySelector(".group\\/sentence > p");
    expect(body?.className).toContain("whitespace-normal");
    expect(body?.className).toContain("leading-6");
    expect(body?.className).toContain("[overflow-wrap:anywhere]");
    expect(body?.className).not.toContain("truncate");
    expect(body?.className).not.toContain("whitespace-nowrap");
  });

  it("右侧行操作平时不占正文空间", async () => {
    serveTranscript(["SPEAKER_00"]);
    const { container } = renderPanel();

    await screen.findByText("第0句");
    const row = container.querySelector(".group\\/sentence");
    const actionRail = screen.getByLabelText("cutSentence").parentElement;
    expect(row?.className).not.toContain("pr-[22px]");
    expect(row?.className).not.toContain("pr-[40px]");
    expect(actionRail?.className).toContain("absolute");
    expect(actionRail?.className).toContain("opacity-0");
    expect(actionRail?.className).not.toContain("group-focus-within/sentence:opacity-100");
  });
});

describe("逐字稿后到:列表挂上之后,滚动还唤得动它", () => {
  /**
   * 用户的截图:页眉写着「198 句 · 3889 字」,正文只到 `01:24.4` 就断了,下面一整片空白。
   *
   * 句子的确是**虚拟化**画的(一小时的稿子上万个词按钮,不能不虚拟化),但这里画不动:逐字稿在接口
   * 那头,面板先渲染空状态 —— 列表那棵子树(连同滚动容器)比这个组件晚一拍才挂上。容器一直用同一个
   * ref 对象的话,`useVirtualRows` 只在第一次、元素还不在的时候看过一眼:此后滚动、改高度都唤不动它,
   * 列表就停在最初算出来的那几十行,往下滚只剩占位的空白。
   *
   * jsdom 不排版:照真浏览器的样子给容器一个高度,往下滚多少、清单的顶边就往上移多少(同
   * MediaLibraryView.virtual.dom.test)。
   */
  it("往下滚:前面的句子收回去,后面的补上来", async () => {
    const transcript = {
      id: "tr1",
      language: "zh",
      segments: Array.from({ length: 60 }, (_, index) => ({
        id: `seg${index}`,
        start_time: index * 10,
        end_time: index * 10 + 5,
        text: `第${index}句`,
        speaker: null,
        tokens: [{ start_time: index * 10, end_time: index * 10 + 5, text: `第${index}句` }],
      })),
    };
    globalThis.fetch = vi.fn(async (input: RequestInfo | URL) => {
      const body = String(input).includes("/transcript") ? transcript : [];
      return new Response(JSON.stringify(body), { status: 200, headers: { "content-type": "application/json" } });
    }) as never;
    const long = {
      id: "s1",
      workspace_id: "w1",
      revision: 1,
      tracks: [
        {
          id: "t1",
          kind: "video",
          clips: [{ id: "c1", asset_id: "a1", asset_kind: "video", timeline_start: 0, src_in: 0, src_out: 600 }],
        },
      ],
    } as never;
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={client}>
        <TranscriptPanel sequence={long} onCutSegment={vi.fn()} />
      </QueryClientProvider>,
    );

    await screen.findByText("第0句");
    const scroller = document.querySelector<HTMLElement>("[data-transcript-scroll]")!;
    const rows = document.querySelector<HTMLElement>("[data-transcript-rows]")!;
    Object.defineProperty(scroller, "clientHeight", { configurable: true, value: 600 });
    rows.getBoundingClientRect = () => ({
      top: -scroller.scrollTop, bottom: 0, left: 0, right: 0, width: 0, height: 0, x: 0, y: 0, toJSON: () => ({}),
    });
    scroller.scrollTop = 2000;
    await act(async () => {
      fireEvent.scroll(scroller);
      await new Promise((resolve) => requestAnimationFrame(() => resolve(null)));
    });

    expect(screen.queryByText("第0句")).toBeNull();
    expect(screen.getByText("第40句")).toBeInTheDocument();
  });
});

describe("在此切一刀之后的行序", () => {
  // 用户撞到的:双语稿里中文和英文同在 0.4 秒开始,在「如果」后面切一刀,
  // 后半截「太年轻的爱注定要分开。」掉到了英文那行下面。切的是一句,两半就该挨着。
  it("被切开的一句,后半截紧跟在前半截后面", async () => {
    const transcript = {
      id: "tr1",
      language: "zh",
      segments: [
        {
          id: "zh",
          start_time: 0.4,
          end_time: 5,
          text: "如果太年轻的爱注定要分开。",
          speaker: null,
          tokens: [
            { start_time: 0.4, end_time: 1.1, text: "如果" },
            { start_time: 1.1, end_time: 5, text: "太年轻的爱注定要分开。" },
          ],
        },
        { id: "en", start_time: 0.4, end_time: 2.9, text: "Iflovethat", speaker: null, tokens: [] },
      ],
    };
    globalThis.fetch = vi.fn(async (input: RequestInfo | URL) => {
      const body = String(input).includes("/transcript") ? transcript : [];
      return new Response(JSON.stringify(body), { status: 200, headers: { "content-type": "application/json" } });
    }) as never;
    const split = {
      id: "s1",
      workspace_id: "w1",
      revision: 2,
      tracks: [
        {
          id: "t1",
          kind: "video",
          clips: [
            { id: "left", asset_id: "a1", asset_kind: "video", timeline_start: 0, src_in: 0, src_out: 1.1 },
            { id: "right", asset_id: "a1", asset_kind: "video", timeline_start: 1.1, src_in: 1.1, src_out: 6 },
          ],
        },
      ],
    } as never;
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const { container } = render(
      <QueryClientProvider client={client}>
        <TranscriptPanel sequence={split} onCutSegment={vi.fn()} />
      </QueryClientProvider>,
    );

    await screen.findByText("如果");
    const rows = [...container.querySelectorAll(".group\\/sentence > p")].map((row) => row.textContent);
    expect(rows.slice(0, 2)).toEqual(["如果", "太年轻的爱注定要分开。"]);
    expect(rows.indexOf("Iflovethat")).toBeGreaterThan(1);
  });
});

/** 转写出一段带两处口癖(呃 / 嗯)的逐字稿:口癖按钮的计数角标要靠它才有数。 */
function serveFillerTranscript() {
  const transcript = {
    id: "tr1",
    language: "zh",
    segments: [
      {
        id: "seg0",
        start_time: 0,
        end_time: 2,
        text: "呃嗯",
        speaker: null,
        tokens: [
          { start_time: 0, end_time: 1, text: "呃" },
          { start_time: 1, end_time: 2, text: "嗯" },
        ],
      },
    ],
  };
  globalThis.fetch = vi.fn(async (input: RequestInfo | URL) => {
    const body = String(input).includes("/transcript") ? transcript : [];
    return new Response(JSON.stringify(body), { status: 200, headers: { "content-type": "application/json" } });
  }) as never;
}

/**
 * 把顶部工具条装齐:逐字稿、存笔记、静音、口癖、按句切分、在此切一刀、生成字幕 —— 7 个动作。
 * 给上 `onSplitPoints` / `onGenerateSubtitles`,后两颗才会渲染。
 */
function renderToolbar({
  onSplitPoints = vi.fn(),
  onGenerateSubtitles = vi.fn(),
}: {
  onSplitPoints?: (cuts: Array<{ clipId: string; srcTimes: number[] }>) => void;
  onGenerateSubtitles?: () => void;
} = {}) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <TranscriptPanel
        sequence={sequenceWith("c1")}
        onCutSegment={vi.fn()}
        onCutRanges={vi.fn()}
        onSplitPoints={onSplitPoints}
        onGenerateSubtitles={onGenerateSubtitles}
      />
    </QueryClientProvider>,
  );
  return { onSplitPoints, onGenerateSubtitles };
}

/** 工具条上的 7 个动作,按读屏 / 悬停里那个名字找。存笔记那颗的名字来自笔记文案(中文)。 */
function toolbarButtons() {
  return [
    screen.getByRole("button", { name: "aiTranscribe" }),
    screen.getByRole("button", { name: "全部存为笔记" }),
    screen.getByRole("button", { name: "silences" }),
    screen.getByRole("button", { name: "fillers" }),
    screen.getByRole("button", { name: "splitBySentence" }),
    screen.getByRole("button", { name: "splitAtWord" }),
    screen.getByRole("button", { name: "transcriptGenerateSubtitles" }),
  ];
}

/** 悬停说明挂在哪:能点的按钮挂在自己身上,点不了的按钮挂在 Hint 套的那层壳上(见 tooltip.tsx)。 */
function hintHost(button: HTMLElement): HTMLElement {
  return (button.closest("[data-hint-disabled]") as HTMLElement | null) ?? button;
}

describe("顶部动作区:图标按钮 + Hint", () => {
  it("7 个动作都是只有图标的按钮:没有可见文字,读屏名字是 aria-label,标准 32px 方钮", async () => {
    serveFillerTranscript();
    renderToolbar();
    await screen.findByText("呃");

    for (const button of toolbarButtons()) {
      expect(button.getAttribute("aria-label"), "icon-only 的按钮必须给读屏一个名字").toBeTruthy();
      // 可见的只有图标;口癖那颗多一个纯数字角标(计数不是动作名)。
      expect(button.textContent ?? "").toMatch(/^\d*$/);
      // 标准档位:32px 的方钮,不许被 flex 压扁。
      expect(button.className).toContain("size-8");
      expect(button.className).toContain("shrink-0");
      // 悬停说明走 Hint,不是原生 title。
      expect(button.hasAttribute("title")).toBe(false);
      expect(hintHost(button).hasAttribute("data-hint-trigger")).toBe(true);
    }
  });

  it("每个图标按钮的 Hint 都有动作名和一句说明", async () => {
    serveFillerTranscript();
    renderToolbar();
    await screen.findByText("呃");

    const expected: Array<[string, string]> = [
      // 这份逐字稿已经转好了:按钮点不了,说明里给的是「都转过了」。
      ["aiTranscribe", "transcribeAllDone"],
      ["全部存为笔记", "把整份逐字稿存成一篇笔记"],
      ["silences", "silencesHint"],
      ["fillers", "fillersHint"],
      ["splitBySentence", "splitBySentenceHint"],
      ["splitAtWord", "splitAtWordHint"],
      ["transcriptGenerateSubtitles", "transcriptGenerateSubtitlesHint"],
    ];
    for (const [name, explanation] of expected) {
      const hint = await readHint(screen.getByRole("button", { name }));
      expect(hint, name).toContain(name);
      expect(hint, name).toContain(explanation);
    }
  });

  it("口癖的计数还在:右上角数字角标,说明里也说清口癖是什么", async () => {
    serveFillerTranscript();
    renderToolbar();
    await screen.findByText("呃");

    const fillers = screen.getByRole("button", { name: "fillers" });
    const badge = fillers.querySelector("[data-count-badge]");
    expect(badge?.textContent).toBe("2");
    expect(fillers.textContent).toBe("2");
    expect(await readHint(fillers)).toContain("fillersHint");
  });

  it("「N 句 · M 字」是一段统计文字,不是按钮", async () => {
    serveTranscript(["SPEAKER_00"]);
    renderToolbar();
    await screen.findByText("第0句");

    const stats = screen.getByText("transcriptStats");
    expect(stats.tagName).toBe("SPAN");
    expect(stats.closest("button")).toBeNull();
  });

  it("点「按句切分」和「生成字幕」还是做原来那件事(回归)", async () => {
    serveTranscript(["SPEAKER_00"]);
    const onSplitPoints = vi.fn();
    const onGenerateSubtitles = vi.fn();
    renderToolbar({ onSplitPoints, onGenerateSubtitles });
    await screen.findByText("第0句");

    await userEvent.click(screen.getByRole("button", { name: "splitBySentence" }));
    expect(onSplitPoints).toHaveBeenCalledWith([{ clipId: "c1", srcTimes: [0] }]);
    await userEvent.click(screen.getByRole("button", { name: "transcriptGenerateSubtitles" }));
    expect(onGenerateSubtitles).toHaveBeenCalledOnce();
  });

  it("点「全部存为笔记」仍然打开保存到笔记的弹窗(回归)", async () => {
    serveTranscript(["SPEAKER_00"]);
    renderToolbar();
    await screen.findByText("第0句");

    await userEvent.click(screen.getByRole("button", { name: "全部存为笔记" }));
    expect(await screen.findByRole("dialog")).toBeInTheDocument();
  });
});

/**
 * 维护者:「注意这两个 tab 的图标的分组」。换成 icon-only 之后,一排同款方钮分不出谁和谁是一类;
 * 分组不能只写在 Hint 里 —— 那要 hover 才知道 —— 要看得见:组间一条发丝线 + 更宽的间距。
 */
describe("顶部动作区的分组", () => {
  function inputNames(group: HTMLElement) {
    return [...group.querySelectorAll("button")].map((button) => button.getAttribute("aria-label"));
  }

  it("三组按语义分开:识别与清理 | 切分与产出 | 文件,每组之间一条发丝线", async () => {
    serveTranscript(["SPEAKER_00"]);
    renderToolbar();
    await screen.findByText("第0句");

    const bar = document.querySelector("[data-transcript-actions]") as HTMLElement;
    expect(bar).not.toBeNull();
    const groups = [...bar.querySelectorAll<HTMLElement>("[data-actions-group]")];
    expect(groups.map((group) => group.dataset.actionsGroup)).toEqual(["cleanup", "produce", "files"]);
    expect(groups.map(inputNames)).toEqual([
      ["aiTranscribe", "silences", "fillers"],
      ["splitBySentence", "splitAtWord", "transcriptGenerateSubtitles"],
      ["全部存为笔记"],
    ]);
    // 两条发丝线,不是 7 颗同款按钮一路排下去。
    const dividers = [...bar.querySelectorAll("[data-actions-divider]")];
    expect(dividers).toHaveLength(2);
    for (const divider of dividers) expect(divider).toHaveAttribute("aria-hidden", "true");
  });

  it("左右两栏:动作在可横滚的左栏,统计钉在右缘、永不滚走", async () => {
    serveTranscript(["SPEAKER_00"]);
    renderToolbar();
    await screen.findByText("第0句");

    const bar = document.querySelector("[data-transcript-actions]") as HTMLElement;
    const scroller = bar.querySelector("[data-actions-scroll]") as HTMLElement;
    const stats = screen.getByText("transcriptStats");

    // 左栏就是那一条**允许**横滚的容器:先能收缩(flex-1 min-w-0),放不下才滚。
    expect(scroller).not.toBeNull();
    expect(scroller.className).toContain("overflow-x-auto");
    expect(scroller.className).toContain("flex-1");
    expect(scroller.className).toContain("min-w-0");
    // 只有横向那一条;不预留滚动条位置(会把图标行撑高),也不写 calc()。
    expect(scroller.className).toContain("overflow-y-hidden");
    expect(scroller.className).not.toContain("scrollbar-gutter");
    expect(scroller.className).not.toContain("calc(");
    // 右栏是同级兄弟,不在滚动容器里 —— 滚的只有左边。宽度按内容(shrink-0)、一行(nowrap)。
    expect(stats.parentElement).toBe(bar);
    expect(scroller.contains(stats)).toBe(false);
    expect(stats.hasAttribute("data-actions-info")).toBe(true);
    expect(stats.className).toContain("shrink-0");
    expect(stats.className).toContain("whitespace-nowrap");
    // 动作全在左栏;左右之间一条发丝线(border-l),和组间那条 ACTION_DIVIDER 同一种细线。
    for (const unit of bar.querySelectorAll("[data-actions-unit]")) {
      expect(scroller.contains(unit)).toBe(true);
    }
    expect(stats.className).toContain("border-l");

    // 左栏的轨道**不折行**:折行就永远滚不起来,「超出滚动」也就无从发生。
    const track = scroller.querySelector("[data-actions-track]") as HTMLElement;
    expect(track).not.toBeNull();
    expect(track.className).toContain("w-max");
    expect(track.className).not.toContain("flex-wrap");
    // 整条动作区只有左栏这一个横向滚动容器。
    expect(bar.querySelectorAll(".overflow-x-auto")).toHaveLength(1);
  });

  it("分组仍然成立:线跟着自己的组,单元不折行、不缩窄", async () => {
    serveTranscript(["SPEAKER_00"]);
    renderToolbar();
    await screen.findByText("第0句");

    const bar = document.querySelector("[data-transcript-actions]") as HTMLElement;
    const units = [...bar.querySelectorAll<HTMLElement>("[data-actions-unit]")];
    expect(units).toHaveLength(3);
    // 一个单元 = 一条线 + 它后面那一组。滚动的是外面那层,单元本身结构不动。
    expect(units.map((unit) => unit.querySelectorAll("[data-actions-divider]").length)).toEqual([0, 1, 1]);
    for (const unit of units) {
      expect(unit.className).toContain("inline-flex");
      expect(unit.className).toContain("shrink-0");
      expect(unit.className).not.toContain("flex-wrap");
      expect(unit.querySelectorAll("[data-actions-group]")).toHaveLength(1);
    }
    // 线在单元里,不是栏的直接子元素 —— 滚到哪,线都跟着自己的组。
    for (const divider of bar.querySelectorAll("[data-actions-divider]")) {
      expect(divider.parentElement).not.toBe(bar);
      expect(divider.parentElement?.hasAttribute("data-actions-unit")).toBe(true);
    }
    // 组内 4px,组间更宽。
    for (const group of bar.querySelectorAll<HTMLElement>("[data-actions-group]")) {
      expect(group.className).toContain("gap-1");
    }
    const track = bar.querySelector("[data-actions-track]") as HTMLElement;
    expect(track.className).toContain("gap-x-1.5");
    for (const unit of units) expect(unit.className).toContain("gap-1.5");
  });
});

/**
 * 维护者:「为何左侧都被切割了导致 icon 的角标不完整」。
 *
 * `overflow-x-auto` 的容器会把 `overflow-y` 算成 `auto`(再显式写 `overflow-y-hidden` 更是直接裁),
 * 裁剪发生在 **padding box 边缘**。图标钮 32px、角标按设计凸在右上 `-top-1`(4px)、焦点环 `ring-2`
 * 往外 2px —— 滚动层的总高若只有内容那 32px,这三样里凸出来的部分全被切掉。
 *
 * jsdom 没有排版,所以这里钉的是**结构和类**:裁剪框自己有没有留出余量、角标到栏之间的祖先链里
 * 还有没有第二个裁剪者。数值由类名对应的刻度说明,和本目录其它布局用例同一种做法。
 */

/** 会纵向裁剪的祖先:只要带 `overflow-*` 的 auto / hidden / scroll / clip 就算(见 `pill.ts` 的说明)。 */
function verticalClippers(from: HTMLElement, stop: HTMLElement): HTMLElement[] {
  const clippers: HTMLElement[] = [];
  for (let node = from.parentElement; node && node !== stop; node = node.parentElement) {
    if (/overflow-(?:x-|y-)?(?:auto|hidden|scroll|clip)/.test(node.getAttribute("class") ?? "")) clippers.push(node);
  }
  return clippers;
}

describe("动作栏的纵向余量", () => {
  it("左栏给自己留出上下余量,行高钉在 40px —— 不再只给内容 32px", async () => {
    serveTranscript(["SPEAKER_00"]);
    renderToolbar();
    await screen.findByText("第0句");

    const bar = document.querySelector("[data-transcript-actions]") as HTMLElement;
    const scroller = bar.querySelector("[data-actions-scroll]") as HTMLElement;

    // 图标钮 32px + 角标向上凸 4px + 焦点环向下 2px ⇒ 至少 38px。py-1 是上下各 4px(共 40px),
    // min-h-10 把这一行钉在同一档(40px = 控件刻度 md):角标正好落在裁剪框里,焦点环还多 2px。
    expect(scroller.className).toContain("py-1");
    expect(scroller.className).toContain("min-h-10");
    // 补的只是纵向空间:横向滚动机制一个字没动,`overflow-y` 也没有被改成 visible。
    expect(scroller.className).toContain("overflow-x-auto");
    expect(scroller.className).toContain("overflow-y-hidden");
    expect(scroller.className).not.toContain("overflow-y-visible");
    expect(scroller.className).not.toContain("calc(");
    // 右栏跟着同一档高度,「N 句 · M 字」不会比左边的图标行矮一截。
    const stats = bar.querySelector("[data-actions-info]") as HTMLElement;
    expect(stats.className).toContain("min-h-10");
  });

  it("口癖的「132」角标不被切:从角标到动作栏,唯一的裁剪者就是留了余量的左栏", async () => {
    serveFillerTranscript();
    renderToolbar();
    await screen.findByText("呃");

    const bar = document.querySelector("[data-transcript-actions]") as HTMLElement;
    const scroller = bar.querySelector("[data-actions-scroll]") as HTMLElement;
    const badge = document.querySelector("[data-count-badge]") as HTMLElement;
    const button = badge.closest("button") as HTMLElement;

    // 角标仍然凸在按钮右上(`-top-1` = 4px)—— 这是对的样子,不把它藏进图标里。
    expect(badge.className).toContain("absolute");
    expect(badge.className).toContain("-top-1");
    // 它自己的定位容器是那颗 32px 的图标钮(不裁剪);再往上唯一的裁剪者是左栏。
    expect(button.className).toContain("relative");
    expect(button.className).toContain("size-8");
    expect(verticalClippers(badge, bar)).toEqual([scroller]);
    // 那个裁剪者上下各留了 4px(>= 角标凸出的 4px),所以「132」整个画得出来。
    expect(scroller.className).toContain("py-1");
    // 焦点环也往上下各出 2px,同样落在余量里;按钮本身没被压窄或压矮。
    expect(button.className).toContain("focus-visible:ring-2");
    expect(button.className).toContain("shrink-0");
  });
});
