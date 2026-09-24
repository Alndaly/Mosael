/** @vitest-environment jsdom */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import React from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

/**
 * 逐字稿页的**转写入口**。
 *
 * 用户撞到的:剪辑页「逐字稿」的空状态只有一段话 —— "外部智能体或后续的转写任务可以通过 API
 * 附加逐字稿" 加一行流程说明,时间线上只有图片时连按钮都没有。读完不知道下一步点哪。
 *
 * 这里钉住每一种状态下用户看到的是什么、点下去发的是哪几个请求:
 * 没有带声音的片段 → 说清楚为什么转不了;有 → 一个主按钮,去重、跳过已转过的;
 * 引擎没装 → 按钮禁用并直达设置「转写」;任务在跑(哪怕是别处发起的)→ 显示转写中。
 */

vi.mock("@/app/preferences", () => ({
  useI18n: () => (key: string) => key,
  usePreferences: () => ({ locale: "zh-CN" }),
}));

import { TranscriptPanel } from "@/features/editor/TranscriptPanel";

Element.prototype.scrollIntoView = vi.fn();

const originalFetch = globalThis.fetch;
afterEach(() => {
  globalThis.fetch = originalFetch;
});

type Clip = { id: string; asset_id: string; asset_kind: string; timeline_start: number; src_in: number; src_out: number };

function clip(id: string, assetId: string, kind: string, start: number): Clip {
  return { id, asset_id: assetId, asset_kind: kind, timeline_start: start, src_in: 0, src_out: 5 };
}

function sequence(video: Clip[], audio: Clip[] = []) {
  return {
    id: "s1",
    workspace_id: "w1",
    revision: 1,
    tracks: [
      { id: "v1", kind: "video", clips: video },
      { id: "a1", kind: "audio", clips: audio },
    ],
  } as never;
}

const transcriptFor = (assetId: string) => ({
  id: `tr-${assetId}`,
  language: "zh",
  segments: [
    {
      id: "seg0",
      start_time: 0,
      end_time: 2,
      text: `${assetId} 说的话`,
      speaker: null,
      tokens: [{ start_time: 0, end_time: 2, text: `${assetId} 说的话` }],
    },
  ],
});

/**
 * 假后端。`transcripts` 里有的素材返回逐字稿,其余 404;转写任务一提交就在下一次查询时成功。
 * 记下每一次「开始转写」请求,好断言发了哪几个。
 */
function serve({
  transcripts = [] as string[],
  asrModels = [] as unknown[],
  jobs = [] as unknown[],
} = {}) {
  const started: string[] = [];
  globalThis.fetch = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    const json = (body: unknown, status = 200) =>
      new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } });
    const transcript = url.match(/\/api\/assets\/([^/]+)\/transcript$/);
    if (transcript) {
      return transcripts.includes(transcript[1]) ? json(transcriptFor(transcript[1])) : json({ detail: "none" }, 404);
    }
    const transcribe = url.match(/\/api\/assets\/([^/?]+)\/transcribe/);
    if (transcribe && init?.method === "POST") {
      started.push(transcribe[1]);
      return json({ id: `job-${transcribe[1]}`, status: "queued", kind: "transcribe", payload: { asset_id: transcribe[1] } });
    }
    const job = url.match(/\/api\/jobs\/([^/?]+)$/);
    if (job) return json({ id: job[1], status: "succeeded", kind: "transcribe", payload: {} });
    if (url.includes("/api/jobs?")) return json(jobs);
    if (url.includes("/api/asr/models")) return json(asrModels);
    return json([]);
  }) as never;
  return { started };
}

function renderPanel(seq: never) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <TranscriptPanel sequence={seq} onCutSegment={vi.fn()} />
    </QueryClientProvider>,
  );
}

describe("逐字稿页的转写入口", () => {
  it("时间线上只有图片 / GIF:说清楚为什么没法转,不摆一个点了也没用的按钮", async () => {
    serve();
    renderPanel(sequence([clip("c1", "img", "image", 0), clip("c2", "gif", "image", 5)]));

    expect(await screen.findByText("transcriptNoAudioClips")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /transcribeTimeline/ })).toBeNull();
    // 旧文案那种"外部智能体通过 API 附加"不再出现。
    expect(screen.queryByText(/API/)).toBeNull();
  });

  it("有带声音的片段:一个主按钮;点下去**每个素材只转一次**,图片跳过", async () => {
    const { started } = serve();
    renderPanel(
      sequence(
        [clip("c1", "img", "image", 0), clip("c2", "vid", "video", 5), clip("c3", "vid", "video", 10)],
        [clip("c4", "voice", "audio", 0)],
      ),
    );

    const button = await screen.findByRole("button", { name: /transcribeTimeline/ });
    await waitFor(() => expect(button).toBeEnabled());
    fireEvent.click(button);

    // 一个接一个:第一个成功后才发第二个。
    await waitFor(() => expect(started).toEqual(["vid", "voice"]));
    expect(started.filter((id) => id === "vid")).toHaveLength(1);
    expect(started).not.toContain("img");
  });

  it("转写引擎没装:按钮禁用,并给一条去设置「转写」的路", async () => {
    const { started } = serve({
      asrModels: [
        { id: "funasr", runtime_ready: false, runtime_checked: true, status: "installed" },
        { id: "whisperx", runtime_ready: false, runtime_checked: true, status: "missing" },
      ],
    });
    renderPanel(sequence([clip("c1", "vid", "video", 0)]));

    expect(await screen.findByText("transcribeNoEngine")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /wfGoConfigure/ })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /transcribeTimeline/ })).toBeDisabled();
    expect(started).toEqual([]);
  });

  it("引擎还没探完(runtime_checked=false)不算没装 —— 拿未知冒充结论会把能用的按钮锁死", async () => {
    serve({ asrModels: [{ id: "funasr", runtime_ready: false, runtime_checked: false, status: "installed" }] });
    renderPanel(sequence([clip("c1", "vid", "video", 0)]));

    const button = await screen.findByRole("button", { name: /transcribeTimeline/ });
    await waitFor(() => expect(button).toBeEnabled());
    expect(screen.queryByText("transcribeNoEngine")).toBeNull();
  });

  it("别处发起的转写正跑着:显示转写中和后端那句状态,不显示「还没有逐字稿」", async () => {
    serve({
      jobs: [{ id: "j9", kind: "transcribe", status: "running", message: "funasr 转写中", payload: { asset_id: "vid" } }],
    });
    renderPanel(sequence([clip("c1", "vid", "video", 0)]));

    expect(await screen.findByText("funasr 转写中")).toBeInTheDocument();
    expect(screen.getAllByText(/transcribing/).length).toBeGreaterThan(0);
    expect(screen.queryByText("transcriptEmpty")).toBeNull();
    expect(screen.queryByRole("button", { name: /transcribeTimeline/ })).toBeNull();
  });

  it("已有逐字稿后又加了一段:顶栏的「AI 转写」标出还差几段,点下去只转新的那段", async () => {
    const { started } = serve({ transcripts: ["vid"] });
    renderPanel(sequence([clip("c1", "vid", "video", 0)], [clip("c2", "voice", "audio", 0)]));

    await screen.findByText("vid 说的话");
    const header = screen.getByRole("button", { name: /aiTranscribe/ });
    expect(header).toHaveAttribute("title", "transcribePendingHint");
    expect(header.querySelector("em")?.textContent).toBe("1");

    fireEvent.click(header);
    await waitFor(() => expect(started).toEqual(["voice"]));
  });
});
