/** @vitest-environment jsdom */
/**
 * 素材详情右栏的「镜头」那一块(ADR 0061 §5)。
 *
 * 三种**互不相同**的状态各测一遍,别让它们混在一起:
 *
 *   - `status: "none"`(没拆过)是一个按钮 + 一句它会做什么;
 *   - `status: "ready"` 有镜头表,但**画面可能一镜都没判**(没有视觉模型 / 判的时候失败):那时逐镜的
 *     判断字段一个都不在,界面只能给机器那一半(镜号、时间、动静、台词)并说清为什么;
 *   - 有表也有判断,才轮到景别 / 运镜 / 画面 / 台词 / 缩略图、复制分镜稿、存成笔记。
 *
 * 文案走**真的中文表**(不是 identity mock):「12 种提示各有一句人话」这件事只有拿真句子才测得出来。
 */
import React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import type { ShotBreakdown, ShotMotionTrack } from "@/api/domains/shots";
import type { Asset } from "@/api/domains/assets";

vi.mock("@/app/preferences", async () => {
  const { zhCN } = await import("@/app/messages/zh-CN");
  const table = zhCN as unknown as Record<string, string>;
  return { useI18n: () => (key: string) => table[key] ?? key };
});

const getShotBreakdown = vi.fn();
const getShotMotionTrack = vi.fn();
const startShotBreakdown = vi.fn();
const listJobs = vi.fn();

vi.mock("@/api/client", async (original) => ({
  ...(await original<typeof import("@/api/client")>()),
  getShotBreakdown: (...args: unknown[]) => getShotBreakdown(...args),
  //: 节奏条那条曲线(自己的画法在 ShotPaceStrip.dom.test.tsx);这里验的是**这一块怎么接它**。
  getShotMotionTrack: (...args: unknown[]) => getShotMotionTrack(...args),
  startShotBreakdown: (...args: unknown[]) => startShotBreakdown(...args),
  listJobs: (...args: unknown[]) => listJobs(...args),
}));

//: 「存成笔记」是仓库既有的那条路,有它自己的测试 —— 这里只验**交给它的东西对不对**。
const noteProps = vi.hoisted(() => ({ current: null as null | { workspaceId: string; variants: { id: string; label: string; markdown: string }[] } }));
vi.mock("@/features/notes/SaveToNote", () => ({
  SaveToNote: ({ workspaceId, variants, trigger }: {
    workspaceId: string;
    variants?: { id: string; label: string; markdown: string }[];
    trigger?: (props: { open: () => void; disabled: boolean; label: string }) => React.ReactNode;
  }) => {
    noteProps.current = { workspaceId, variants: variants ?? [] };
    return <>{trigger?.({ open: () => {}, disabled: false, label: "note" })}</>;
  },
}));

import { ShotBreakdownPanel } from "./ShotBreakdownPanel";

const asset = {
  id: "clip",
  workspace_id: "ws",
  name: "片头.mp4",
  kind: "video",
  source: "imported",
  media_info: { duration: 40, width: 1920, height: 1080, fps: 24 },
} as unknown as Asset;

/** 机器量的那一半 —— 每一镜都有。 */
const measured = { id: "S01", start: 0, end: 2.6, seconds: 2.6, motion: 3.2, dialogue: "" };

const judged = [
  {
    ...measured,
    id: "S01",
    start: 0,
    size: "medium",
    category: "establishing",
    camera: ["push-in"],
    transition_in: "cut",
    rhythm: "hook",
    frame: "女孩推门走进咖啡馆",
    prompt: "中景,女孩推门走进咖啡馆,镜头缓缓推近",
  },
  {
    ...measured,
    id: "S02",
    start: 12.4,
    end: 15,
    dialogue: "你要点什么?",
    size: "close",
    category: "dialogue",
    camera: ["static"],
    transition_in: "dissolve",
    rhythm: "setup",
    frame: "菜单特写",
    prompt: "特写,菜单上的一行字",
  },
];

function ready(over: Partial<ShotBreakdown> = {}): ShotBreakdown {
  return {
    asset_id: "clip",
    status: "ready",
    id: "b1",
    lang: "zh",
    shots: judged,
    sheets: [],
    describe: { provider: "kimi", model: "m1", batches: 1, judged_batches: 1, error: "" },
    hints: [],
    stats: {},
    report_markdown: "# 镜头表\n\nS01 中景 0.0–2.6s",
    storyboard_markdown: "## 分镜提示词\n\n1. 中景,女孩推门走进咖啡馆,镜头缓缓推近",
    updated_at: "2026-10-16T05:00:00",
    ...over,
  } as ShotBreakdown;
}

const none = { asset_id: "clip", status: "none", shots: [], hints: [], describe: {} } as unknown as ShotBreakdown;

/** 整条动静曲线(`GET /assets/{id}/shots/track`)。缺省是量过的:40 秒、5Hz、200 个点。 */
function track(over: Partial<ShotMotionTrack> = {}): ShotMotionTrack {
  const values = new Array<number>(200).fill(6);
  return {
    asset_id: "clip",
    status: "ready",
    hz: 5,
    points: values.length,
    duration: 40,
    first_sample_seconds: 0.2,
    sample_interval_seconds: 0.2,
    digest: "sha256:0123456789abcdef0123",
    values,
    ...over,
  } as ShotMotionTrack;
}

/** 没量过的那一种:后端照旧 200,`values` 空。 */
const noTrack = track({ status: "none", hz: 0, points: 0, duration: 0, first_sample_seconds: 0, sample_interval_seconds: 0, digest: "", values: [] });

function show(panel = <ShotBreakdownPanel asset={asset} onSeek={vi.fn()} />) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: Infinity } } });
  const wrap = (node: React.ReactElement) => <QueryClientProvider client={client}>{node}</QueryClientProvider>;
  const view = render(wrap(panel));
  return { ...view, replay: (node: React.ReactElement) => view.rerender(wrap(node)) };
}

beforeEach(() => {
  getShotBreakdown.mockReset();
  getShotMotionTrack.mockReset();
  startShotBreakdown.mockReset();
  listJobs.mockReset();
  listJobs.mockResolvedValue([]);
  //: 这一份用例集测的是「镜头」那四种状态;曲线缺省给「没量过」,要曲线的自己覆盖。
  getShotMotionTrack.mockResolvedValue(noTrack);
  noteProps.current = null;
  Object.assign(navigator, { clipboard: { writeText: vi.fn(async () => undefined) } });
});
afterEach(cleanup);

//: ① 没拆过:**不是** 404,是一个正常的回答 —— 界面给一颗按钮,点了排后台任务。
it("没拆过:显示「拆镜头」,点了排一条 shot_breakdown 任务", async () => {
  getShotBreakdown.mockResolvedValue(none);
  const job = { id: "job1", kind: "shot_breakdown", status: "queued", message: "拆镜头排队中", progress: 0, payload: { asset_id: "clip" } };
  startShotBreakdown.mockImplementation(async () => {
    //: 后端是**建完任务才**回这一条,所以任务列表里立刻就有它(还在跑的都会被列出来)。
    listJobs.mockResolvedValue([job]);
    return job;
  });

  show();
  const button = await screen.findByRole("button", { name: /拆镜头/ });
  //: 按钮旁边要说清它会花多久、花不花钱(有视觉模型时逐批判画面)。
  expect(screen.getByText(/不花钱/)).toBeTruthy();
  expect(screen.getByText(/视觉模型/)).toBeTruthy();

  fireEvent.click(button);
  await waitFor(() => expect(startShotBreakdown).toHaveBeenCalledWith("clip"));
  //: 排上之后当场就有「进行中」的样子,不用等下一轮轮询。
  expect(await screen.findByText(/排队中/)).toBeTruthy();
});

//: 拆过之后那颗按钮改成「重拆」,并说清它会覆盖 —— 一份素材只有一份表(ADR 0061 待拍板 2)。
it("拆过:「拆镜头」变成「重拆」,并说明会覆盖现有的表", async () => {
  getShotBreakdown.mockResolvedValue(ready());
  show();
  expect(await screen.findByRole("button", { name: /重拆/ })).toBeTruthy();
  expect(screen.getByText(/覆盖/)).toBeTruthy();
});

//: 已经有一条在跑(比如刚才关掉弹窗又打开):按任务列表里的那条显示进行中,不再给按钮。
it("有任务在跑:显示进行中,按钮点不了", async () => {
  getShotBreakdown.mockResolvedValue(ready());
  listJobs.mockResolvedValue([
    { id: "job9", kind: "shot_breakdown", status: "running", progress: 0.5, message: "逐镜判画面中", payload: { asset_id: "clip" } },
  ]);
  show();
  //: 老的那一列镜头还在(判到一半也有东西看),上面挂一条「在做」。
  expect(await screen.findByText(/逐镜判画面中/)).toBeTruthy();
  expect(screen.getByText("S01")).toBeTruthy();
});

//: ② 拆过:一列镜头 —— 缩略图、镜号 + 时间、景别 / 运镜(中文标签)、画面描述、台词。
it("拆过:每一镜都有缩略图、镜号时间、景别运镜的中文、画面描述、台词", async () => {
  getShotBreakdown.mockResolvedValue(ready());
  const { container } = show();

  await waitFor(() => expect(container.querySelectorAll("[data-shot-row]")).toHaveLength(2));
  const rows = [...container.querySelectorAll<HTMLElement>("[data-shot-row]")];

  //: 镜号 + `m:ss.d · 秒数`。
  expect(rows[0].textContent).toContain("S01");
  expect(rows[0].textContent).toContain("00:00.0");
  expect(rows[0].textContent).toContain("2.6s");
  expect(rows[1].textContent).toContain("00:12.4");

  //: 封闭词表给的是中文标签,不是后端那些原词。
  expect(rows[0].textContent).toContain("中景");
  expect(rows[0].textContent).toContain("推");
  expect(rows[0].textContent).not.toContain("push-in");
  expect(rows[1].textContent).toContain("特写");
  expect(rows[1].textContent).toContain("固定");

  expect(rows[0].textContent).toContain("女孩推门走进咖啡馆");
  expect(rows[1].textContent).toContain("你要点什么?");

  //: 缩略图请求的是那一镜的 a 帧(`frames/{S01a.jpg}`)。
  const thumbs = [...rows].map((row) => row.querySelector("img")?.getAttribute("src") ?? "");
  expect(thumbs[0]).toContain("/shots/frames/S01a.jpg");
  expect(thumbs[1]).toContain("/shots/frames/S02a.jpg");
});

//: 缩略图读不出来(素材被清理 / 重拆过 / 那一帧没截到)时要有兜底,不能是浏览器的破图图标。
it("缩略图 404:换成中性图标 + 一句说明,不留破图", async () => {
  getShotBreakdown.mockResolvedValue(ready());
  const { container } = show();

  await waitFor(() => expect(container.querySelectorAll("[data-shot-row]")).toHaveLength(2));
  const [first] = [...container.querySelectorAll<HTMLElement>("[data-shot-row]")];
  const img = first.querySelector("img");
  expect(img).not.toBeNull();

  fireEvent.error(img!);

  expect(first.querySelector("img")).toBeNull();
  expect(first.querySelector("[data-shot-frame-missing]")).not.toBeNull();
});

//: ④ 有表但一镜都没判过:只有机器那一半,不炸,而且说得出为什么。
it("没判过画面:只显示机器量的那一半,并说明原因", async () => {
  getShotBreakdown.mockResolvedValue(
    ready({
      shots: [{ ...measured, start: 0.4 }],
      describe: { error: "没有可用的视觉模型,请先在设置里配一条" },
      hints: [{ shot: "", kind: "not_described", field: "", value: "" }],
      report_markdown: "# 镜头表",
      storyboard_markdown: "",
    }),
  );
  const { container } = show();

  await waitFor(() => expect(container.querySelectorAll("[data-shot-row]")).toHaveLength(1));
  const row = container.querySelector<HTMLElement>("[data-shot-row]")!;
  //: 机器量的那一半照旧:镜号、时间、动静。
  expect(row.textContent).toContain("S01");
  expect(row.textContent).toContain("00:00.4");
  //: 判过的键一个都不在 —— 不许拿空值硬画一个「无景别」出来。
  expect(row.textContent).not.toContain("无景别");
  expect(row.textContent).not.toContain("固定");
  //: 为什么没判:界面自己那句 + 后端给的人话。
  expect(screen.getByText(/画面还没判过/)).toBeTruthy();
  expect(screen.getByText(/没有可用的视觉模型/)).toBeTruthy();
});

//: ⑤ 对账 / 节奏的提示要有地方给人看 —— 12 种各一句人话,值替进去,不露出 key。
it("提示:12 种都翻成人话,值替进去", async () => {
  const kinds = [
    ["unknown_word", "S01", "dolly"],
    ["camera_corrected", "S01", "push-in"],
    ["static_but_moving", "S02", "18.4"],
    ["thin_frame", "S02", "氛围感"],
    ["flat_stretch", "S03", "beat"],
    ["batch_unreadable", "S01", "S25"],
    ["batch_failed", "S01", "S25"],
    ["not_judged", "S03", ""],
    ["not_described", "", ""],
    ["truncated", "", "240"],
    ["no_hook", "", ""],
    ["payoff_without_setup", "S04", ""],
  ] as const;

  getShotBreakdown.mockResolvedValue(
    ready({ hints: kinds.map(([kind, shot, value]) => ({ kind, shot, value, field: kind === "unknown_word" ? "camera" : "" })) }),
  );
  const { container } = show();

  await waitFor(() => expect(container.querySelectorAll("[data-shot-hint]")).toHaveLength(12));
  const lines = [...container.querySelectorAll<HTMLElement>("[data-shot-hint]")].map((one) => one.textContent ?? "");

  for (const line of lines) {
    expect(line).not.toMatch(/^shotHint/);
    expect(line).not.toContain("{");
    expect(line.trim().length).toBeGreaterThan(4);
  }
  //: 值真的替进了句子里(不是只把 key 换成一句没有值的话)。
  expect(lines[0]).toContain("dolly");
  expect(lines[0]).toContain("S01");
  expect(lines[5]).toContain("S25");
  expect(lines[9]).toContain("240");
  expect(screen.getByText(/开篇 5 秒/)).toBeTruthy();
});

//: ⑥ 「复制分镜提示词」:后端拼好的分镜稿原样进剪贴板。
it("复制分镜提示词:把分镜稿写进剪贴板", async () => {
  getShotBreakdown.mockResolvedValue(ready());
  show();

  fireEvent.click(await screen.findByRole("button", { name: /复制分镜提示词/ }));
  await waitFor(() =>
    expect(navigator.clipboard.writeText).toHaveBeenCalledWith("## 分镜提示词\n\n1. 中景,女孩推门走进咖啡馆,镜头缓缓推近"),
  );
});

//: 后端没给分镜稿时(表是老的、或者只有机器那一半),用各镜的 prompt 拼一份 —— 按钮不能点了什么都不给。
it("复制分镜提示词:后端没拼时用各镜的 prompt 拼", async () => {
  getShotBreakdown.mockResolvedValue(ready({ storyboard_markdown: "" }));
  show();

  fireEvent.click(await screen.findByRole("button", { name: /复制分镜提示词/ }));
  await waitFor(() => expect(navigator.clipboard.writeText).toHaveBeenCalled());
  const copied = vi.mocked(navigator.clipboard.writeText).mock.calls[0][0];
  expect(copied).toContain("S01");
  expect(copied).toContain("中景,女孩推门走进咖啡馆,镜头缓缓推近");
  expect(copied).toContain("特写,菜单上的一行字");
});

//: ⑦ 「存成笔记」走仓库既有那条路(SaveToNote),把镜头表和分镜提示词两份正文都交给它挑。
it("存成笔记:交给 SaveToNote 的是这一份素材和工作区,正文是镜头表和分镜稿", async () => {
  getShotBreakdown.mockResolvedValue(ready());
  show();

  const note = await screen.findByRole("button", { name: "note" });
  expect(note).toBeTruthy();
  expect(noteProps.current?.workspaceId).toBe("ws");
  expect(noteProps.current?.variants.map((one) => one.id)).toEqual(["report", "storyboard"]);
  expect(noteProps.current?.variants[0].markdown).toContain("镜头表");
  expect(noteProps.current?.variants[1].markdown).toContain("分镜提示词");
});

//: 一镜都没判过时没有分镜稿可复制 —— 按钮点不了,并且说得出为什么。
it("没判过画面:分镜提示词那颗按钮点不了", async () => {
  getShotBreakdown.mockResolvedValue(
    ready({ shots: [measured], storyboard_markdown: "", hints: [], describe: { error: "没有可用的视觉模型" } }),
  );
  show();
  expect(await screen.findByRole("button", { name: /复制分镜提示词/ })).toBeDisabled();
});

//: ⑧ 节奏条(ADR 0061 §5):整条动静曲线画在逐镜列表**上面**;点条上某一镜走的是详情那条 `onSeek`
//: —— 和点一行同一条路,不另造第二个跳转机制。
it("节奏条:画在逐镜列表上面,点条上某一镜报的是它的 start", async () => {
  getShotBreakdown.mockResolvedValue(ready());
  getShotMotionTrack.mockResolvedValue(track());
  const onSeek = vi.fn();
  const { container } = show(<ShotBreakdownPanel asset={asset} onSeek={onSeek} />);

  const strip = await waitFor(() => {
    const found = container.querySelector<HTMLElement>("[data-shot-pace]");
    expect(found).not.toBeNull();
    return found!;
  });
  //: 曲线 + 两处刀口(和镜头表里那两镜对得上)。
  expect(strip.querySelector("[data-shot-pace-svg]")).not.toBeNull();
  expect(strip.querySelectorAll("[data-pace-cut]")).toHaveLength(2);
  expect(strip.querySelector("[data-pace-cut]")?.getAttribute("data-pace-cut")).toBe("S01");
  //: 在逐镜列表**上面**。
  const rows = container.querySelector("[data-shot-row]")!;
  expect(strip.compareDocumentPosition(rows) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();

  fireEvent.click(strip.querySelector('[data-shot-region="S02"]')!);
  expect(onSeek).toHaveBeenCalledWith(12.4);
});

//: 当前镜高亮接的是**播放器报上来的秒数**,不是这一块自己猜的。
it("节奏条:当前镜跟着播放器报上来的秒数走", async () => {
  getShotBreakdown.mockResolvedValue(ready());
  getShotMotionTrack.mockResolvedValue(track());
  const panel = (playhead: number) => <ShotBreakdownPanel asset={asset} onSeek={vi.fn()} playhead={playhead} />;
  const { container, replay } = show(panel(13));

  await waitFor(() => expect(container.querySelector("[data-pace-current]")).not.toBeNull());
  expect(container.querySelector("[data-pace-current]")!.getAttribute("data-pace-current")).toBe("S02");

  replay(panel(0.5));
  expect(container.querySelector("[data-pace-current]")!.getAttribute("data-pace-current")).toBe("S01");
});

//: ⑨ 没拆过:连刀口都没有,节奏条**不出现**(不是画一条空的)。
it("没拆过:不出现节奏条,也不问曲线", async () => {
  getShotBreakdown.mockResolvedValue(none);
  const { container } = show();
  await screen.findByRole("button", { name: /拆镜头/ });
  expect(container.querySelector("[data-shot-pace]")).toBeNull();
  expect(getShotMotionTrack).not.toHaveBeenCalled();
});

//: ⑩ `status: "none"`(没量过 / 老行没记):不画条,一句话说清拆一次就有。
it("曲线没量过:不画条,说明拆一次就有", async () => {
  getShotBreakdown.mockResolvedValue(ready());
  const { container } = show();
  await waitFor(() => expect(container.querySelector('[data-shot-pace-status="none"]')).not.toBeNull());
  expect(container.querySelector("[data-shot-pace-svg]")).toBeNull();
  //: 逐镜那一列照旧在 —— 曲线没了不该带走镜头表。
  expect(container.querySelectorAll("[data-shot-row]")).toHaveLength(2);
});

//: ⑪ `status: "missing"`(库里记着、盘上那份没了):说出 points 与 digest,并给重拆的出口 ——
//: 出口排的是**同一条**拆镜头任务(和上面那颗按钮同一条路)。
it("曲线盘上丢了:说出 points 与 digest,重拆的出口排的是拆镜头任务", async () => {
  getShotBreakdown.mockResolvedValue(ready());
  getShotMotionTrack.mockResolvedValue(
    track({ status: "missing", values: [], points: 18000, digest: "sha256:deadbeefdeadbeef" }),
  );
  startShotBreakdown.mockResolvedValue({ id: "job2", kind: "shot_breakdown", status: "queued", message: "拆镜头排队中", payload: { asset_id: "clip" } });
  const { container } = show();

  const line = await waitFor(() => {
    const found = container.querySelector<HTMLElement>('[data-shot-pace-status="missing"]');
    expect(found).not.toBeNull();
    return found!;
  });
  expect(line.textContent).toContain("18000");
  expect(line.textContent).toContain("deadbeefdead");
  expect(container.querySelector("[data-shot-pace-svg]")).toBeNull();

  fireEvent.click(within(line).getByRole("button", { name: /重拆/ }));
  await waitFor(() => expect(startShotBreakdown).toHaveBeenCalledWith("clip"));
});

//: 曲线那条请求自己失败时,别把整块拖下水:一句话,逐镜列表照旧。
it("曲线取不到:说一句,镜头列表照旧", async () => {
  getShotBreakdown.mockResolvedValue(ready());
  getShotMotionTrack.mockRejectedValue(new Error("boom"));
  const { container } = show();
  await waitFor(() => expect(container.querySelector('[data-shot-pace-status="error"]')).not.toBeNull());
  expect(container.querySelectorAll("[data-shot-row]")).toHaveLength(2);
});
