/** @vitest-environment jsdom */
/**
 * 「镜头」块上面那条**节奏条**:整条动静曲线 + 刀口 + 当前镜高亮 + 点一下就跳。
 *
 * 这里只测这一条自己的画法(它**不碰播放器**:跳转是把秒数报给外面,由详情交给左栏那个播放器)。
 * 五条要钉住的:
 *
 * ① **横轴**:峰落在它那一秒对应的列上,刀口画在 `shots[].start` 上;
 * ② **每列取窗口最大值** —— 一组 `[0,0,255,0,0]` 里的尖峰必须留住(取平均会抹成一条矮线);
 * ③ **点某一镜 = 报那一镜的 `start`**,键盘也能走到;
 * ④ **`none` / `missing` 两种降级**:不画条,各有一句人话(后者还要有重拆的出口);
 * ⑤ **时间轴**按 `first_sample_seconds + i × sample_interval_seconds` —— 第 0 个点不在 0 秒,
 *    数据故意把 `hz` 和这两个字段拆开:谁按 `i/hz` 读,峰就会错位(错位到哪一列都写死在断言里)。
 *
 * 宽度:jsdom 没有版面,`getBoundingClientRect()` 恒为 0。这里给它一个确定的 80,列数就确定了 ——
 * 断言里的列号都从渲染出来的 `viewBox` 读,不写死「应该是 600 列」这种数。
 */
import React from "react";
import { cleanup, fireEvent, render, within } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import type { Shot, ShotMotionTrack } from "@/api/domains/shots";

vi.mock("@/app/preferences", async () => {
  const { zhCN } = await import("@/app/messages/zh-CN");
  const table = zhCN as unknown as Record<string, string>;
  return { useI18n: () => (key: string) => table[key] ?? key };
});

import { ShotPaceStrip } from "./ShotPaceStrip";

/** 条在 jsdom 里量不出宽度 —— 给它一个确定的宽度(列数 = 这个数)。 */
const LANE_WIDTH = 80;
const LANE_HEIGHT = 32;
/** 曲线的整段时长(秒)= 横轴满格。 */
const SPAN = 4;

const shots = [
  { id: "S01", start: 0, end: 1, seconds: 1, motion: 12.5 },
  { id: "S02", start: 1, end: 2.5, seconds: 1.5, motion: 40 },
  { id: "S03", start: 2.5, end: 4, seconds: 1.5, motion: 3 },
] as Shot[];

function trackOf(over: Partial<ShotMotionTrack> = {}): ShotMotionTrack {
  //: 缺省是一条画得出来的曲线:t = 0.2 … 4.0,每处 8。
  const values = new Array<number>(20).fill(8);
  return {
    asset_id: "clip",
    status: "ready",
    hz: 5,
    points: values.length,
    duration: SPAN,
    first_sample_seconds: 0.2,
    sample_interval_seconds: 0.2,
    digest: "sha256:0123456789abcdef0123",
    values,
    ...over,
  } as ShotMotionTrack;
}

function show(over: { track?: ShotMotionTrack; playhead?: number; onSeek?: (seconds: number) => void; onRebuild?: () => void } = {}) {
  const onSeek = vi.fn(over.onSeek ?? (() => {}));
  const onRebuild = vi.fn(over.onRebuild ?? (() => {}));
  const props = (playhead: number) => (
    <ShotPaceStrip
      shots={shots}
      track={over.track ?? trackOf()}
      duration={SPAN}
      playhead={playhead}
      onSeek={onSeek}
      onRebuild={onRebuild}
    />
  );
  const view = render(props(over.playhead ?? 0));
  return { ...view, onSeek, onRebuild, at: (playhead: number) => view.rerender(props(playhead)) };
}

/** 列数从渲染出来的 `viewBox` 读 —— 断言不依赖组件里写死的常数。 */
function columnsOf(container: HTMLElement): number {
  const svg = container.querySelector("[data-shot-pace-svg]");
  expect(svg).not.toBeNull();
  return Number(svg!.getAttribute("viewBox")!.split(/\s+/)[2]);
}

/** 第几秒落在第几列 —— 照横轴的定义重新算一遍(不用组件里的那个函数)。 */
function columnAt(seconds: number, columns: number): number {
  return Math.floor((seconds / SPAN) * columns);
}

const rectAt = (container: HTMLElement, column: number) => container.querySelector(`[data-pace-column="${column}"]`);
const cutOf = (container: HTMLElement, id: string) => container.querySelector(`[data-pace-cut="${id}"]`);

beforeEach(() => {
  vi.spyOn(HTMLElement.prototype, "getBoundingClientRect").mockImplementation(
    () => new DOMRect(0, 0, LANE_WIDTH, LANE_HEIGHT),
  );
});
afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

//: ① 峰落在它那一秒对应的列上;刀口画在每一镜的 start 上;首尾有时间刻度。
it("ready:峰在自己那一列,刀口在每一镜的 start 上", () => {
  //: 20 个采样,t = 0.2 … 4.0(`first 0.2 + i × 0.2`);第 11 个(t = 2.2)是尖峰。
  const values = Array.from({ length: 20 }, (_, index) => (index === 10 ? 255 : 8));
  const { container } = show({ track: trackOf({ values, points: values.length }) });
  const columns = columnsOf(container);

  const peak = container.querySelector('[data-pace-value="255"]');
  expect(peak).not.toBeNull();
  //: 峰的位置 = 它那一秒在横轴上的列(2.2 / 4 × 列数)。
  expect(Number(peak!.getAttribute("data-pace-column"))).toBe(columnAt(2.2, columns));
  expect(Number(peak!.getAttribute("x"))).toBe(columnAt(2.2, columns));
  //: 整段都该有东西:最后一个采样落在最后一列上(横轴 = 整段时长)。
  expect(rectAt(container, columns - 1)).not.toBeNull();
  //: 刀口 = 每一镜的 start。
  expect(Number(cutOf(container, "S02")!.getAttribute("x"))).toBe(columnAt(1, columns));
  expect(Number(cutOf(container, "S03")!.getAttribute("x"))).toBe(columnAt(2.5, columns));
  expect(Number(cutOf(container, "S02")!.getAttribute("height"))).toBe(LANE_HEIGHT);
  //: 条要读得懂:纵轴有峰值、横轴有首尾。
  const text = container.textContent ?? "";
  expect(text).toContain("峰值 255");
  expect(text).toContain("00:00.0");
  expect(text).toContain("00:04.0");
});

//: ② 每 1px(这里是一列)取**窗口最大值**:平均会把这个尖峰抹平,最大值不会。
it("每列取窗口最大值:窗口里的尖峰保住了(取平均只剩 1/5 高)", () => {
  //: 400 个采样、5 个落一列:第 203 个(t = 0.01 + 202 × 0.01 = 2.03)是 255,同窗口另外 4 个是 0。
  //: 取平均是 51 —— 画出来只有 32 × 51/255 ≈ 6.4,尖峰就没了。
  const values = new Array<number>(400).fill(0);
  values[202] = 255;
  const { container } = show({ track: trackOf({ values, points: values.length, first_sample_seconds: 0.01, sample_interval_seconds: 0.01 }) });
  const columns = columnsOf(container);

  const barColumn = columnAt(2.03, columns);
  const bar = rectAt(container, barColumn);
  expect(bar).not.toBeNull();
  //: 存下来的是窗口最大值(255),不是均值(51 → 只有 6.4 高)。
  expect(Number(bar!.getAttribute("data-pace-value"))).toBe(255);
  expect(Number(bar!.getAttribute("height"))).toBe(LANE_HEIGHT);
  //: 同一列还是那一根(另外 4 个采样是 0,不各画一根)。
  expect(container.querySelectorAll(`[data-pace-column="${barColumn}"]`)).toHaveLength(1);
  //: 全 0 的那几列什么都不画。
  expect(rectAt(container, 0)).toBeNull();
});

//: ③ 点条上的某一镜 = 把它的 start 报上去(复用详情那条 seekTo,不另造机制)。
it("点条上某一镜:报的是那一镜的 start", () => {
  const { container, onSeek } = show();
  fireEvent.click(container.querySelector('[data-shot-region="S02"]')!);
  expect(onSeek).toHaveBeenCalledWith(1);
  fireEvent.click(container.querySelector('[data-shot-region="S03"]')!);
  expect(onSeek).toHaveBeenLastCalledWith(2.5);
});

//: ③b 键盘也走得到:每一镜是一个可聚焦的按钮,回车 / 空格都跳。
it("键盘:条上的镜能 Tab 到,回车和空格都跳", () => {
  const { container, onSeek } = show();
  const region = container.querySelector<HTMLElement>('[data-shot-region="S03"]')!;
  expect(region.getAttribute("tabindex")).toBe("0");
  expect(region.getAttribute("role")).toBe("button");
  region.focus();
  expect(document.activeElement).toBe(region);
  fireEvent.keyDown(region, { key: "Enter" });
  fireEvent.keyDown(region, { key: " " });
  expect(onSeek.mock.calls.map((one) => one[0])).toEqual([2.5, 2.5]);
});

//: ②c 悬停 / 读屏的说明:镜号、起止、时长、实测动静都在里面。
it("每一镜的说明里有镜号、起止、时长和实测动静", () => {
  const { container } = show();
  const label = container.querySelector('[data-shot-region="S02"]')!.getAttribute("aria-label") ?? "";
  expect(label).toContain("S02");
  expect(label).toContain("00:01.0");
  expect(label).toContain("00:02.5");
  expect(label).toContain("1.5");
  expect(label).toContain("40");
});

//: ④a 没量过:不画条,一句话说清「拆一次就有」。
it("status none:不画条,说明拆一次就有", () => {
  const { container } = show({
    track: trackOf({ status: "none", hz: 0, points: 0, duration: 0, first_sample_seconds: 0, sample_interval_seconds: 0, digest: "", values: [] }),
  });
  expect(container.querySelector("[data-shot-pace-svg]")).toBeNull();
  const line = container.querySelector('[data-shot-pace-status="none"]');
  expect(line).not.toBeNull();
  expect(line!.textContent).toMatch(/拆/);
});

//: ④b 库里记着、盘上那份没了:把 points 与 digest 说出来,并给「重拆一次」的出口。
it("status missing:说出 points 与 digest,并给重拆的出口", () => {
  const onRebuild = vi.fn();
  const { container } = show({
    track: trackOf({ status: "missing", points: 18000, digest: "sha256:0123456789abcdef0123", values: [] }),
    onRebuild,
  });
  expect(container.querySelector("[data-shot-pace-svg]")).toBeNull();
  const line = container.querySelector<HTMLElement>('[data-shot-pace-status="missing"]')!;
  expect(line.textContent).toContain("18000");
  expect(line.textContent).toContain("0123456789ab");
  fireEvent.click(within(line).getByRole("button"));
  expect(onRebuild).toHaveBeenCalledTimes(1);
});

//: ⑤ 时间轴读的是两个数,不是自己拿 `i/hz` 算:这一条数据里两者故意错开。
it("时间轴按 first + i × interval 读:第 0 点不在 0 秒,按 i/hz 会错位", () => {
  //: hz = 5(1/hz = 0.2),而 first = 0.3、interval = 0.2。
  //: 第 1 个点在 0.3s(不是 0);第 6 个点在 1.3s —— 按 i/hz 读会落到 1.0s,差 6 列。
  const values = new Array<number>(20).fill(0);
  values[0] = 200;
  values[5] = 255;
  const { container } = show({ track: trackOf({ values, points: values.length, first_sample_seconds: 0.3 }) });
  const columns = columnsOf(container);

  expect(Number(container.querySelector('[data-pace-value="200"]')!.getAttribute("data-pace-column")))
    .toBe(columnAt(0.3, columns));
  expect(Number(container.querySelector('[data-pace-value="255"]')!.getAttribute("data-pace-column")))
    .toBe(columnAt(1.3, columns));
  //: 第 0 列(0 秒)上没有东西;按 i/hz 算出来的那一列上也没有。
  expect(rectAt(container, 0)).toBeNull();
  expect(rectAt(container, columnAt(1, columns))).toBeNull();
});

//: ⑥ 当前镜高亮跟着播放位置走,换一镜就换一段。
it("当前镜跟着播放位置高亮", () => {
  const { container, at } = show({ playhead: 2 });
  const band = () => container.querySelector("[data-pace-current]")!;
  const columns = columnsOf(container);
  expect(band().getAttribute("data-pace-current")).toBe("S02");
  expect(Number(band().getAttribute("x"))).toBe(columnAt(1, columns));
  expect(Number(band().getAttribute("width"))).toBe(columnAt(2.5, columns) - columnAt(1, columns));

  at(3);
  expect(band().getAttribute("data-pace-current")).toBe("S03");
  expect(Number(band().getAttribute("x"))).toBe(columnAt(2.5, columns));
});

//: 纵轴还有一个刻度:动静整体很小的时候说清「满格」是多少,不然一条矮线看不出是不是没量到。
it("纵轴:动静小的时候标出满格", () => {
  const values = new Array<number>(20).fill(6);
  const { container } = show({ track: trackOf({ values, points: values.length }) });
  expect(container.textContent).toContain("峰值 6");
  expect(container.textContent).toContain("满格 32");
});
