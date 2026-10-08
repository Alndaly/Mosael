/** @vitest-environment jsdom */
import React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { Job } from "@/api/client";

const h = vi.hoisted(() => ({
  error:
    "ARK request failed: https://ark.cn-beijing.volces.com/api/v3/contents/generations/tasks; " +
    '{"code":"InputImageSensitiveContentDetected.PrivacyInformation","request_id":"021788160646919b9f489096afc36acf450c00ec3935d23a968bb2"}',
  events: [] as Array<Record<string, unknown>>,
  //: 详情接口交回的那一份(带 `result`);列表里点开的那一行不带它。
  full: null as Record<string, unknown> | null,
  cancelled: [] as string[],
  regenerated: [] as string[],
}));

vi.mock("@/app/preferences", () => ({
  useI18n: () => (key: string) => key,
  usePreferences: () => ({ locale: "zh-CN" }),
}));
vi.mock("@/components/jobs/jobKinds", () => ({
  useJobKinds: () => ({ kindOf: () => ({ label: "工作流" }) }),
}));
vi.mock("@/api/client", () => ({
  //: 只按 id 取交出来的那几份(不再把整个素材库拉回来再找)。
  getAsset: async (id: string) =>
    ({ "img-1": { id: "img-1", kind: "image", name: "三视图" }, "aud-1": { id: "aud-1", kind: "audio", name: "旁白" } })[id],
  assetThumbnailUrl: (id: string) => `/thumb/${id}`,
  assetPreviewUrl: (id: string) => `/preview/${id}`,
  assetFileUrl: (id: string) => `/file/${id}`,
  getJob: async () => h.full,
  listJobChildren: async () => [],
  listJobEvents: async () => h.events,
  cancelJob: async (id: string) => {
    h.cancelled.push(id);
    return null;
  },
  regenerateAssetProxy: async (id: string) => {
    h.regenerated.push(id);
    return null;
  },
}));
vi.mock("@/api/errorMessage", () => ({ errorText: (e: Error) => e.message }));
vi.mock("sonner", () => ({ toast: { error: vi.fn(), success: vi.fn() } }));
const lightbox = vi.hoisted(() => ({ openImagePreview: vi.fn() }));
vi.mock("@/components/app/image-preview", () => ({ useImagePreview: () => lightbox }));

import { JobDetailDialog } from "./JobDetailDialog";

beforeEach(() => {
  h.full = null;
});

const job = {
  id: "job-1",
  workspace_id: "workspace-1",
  kind: "ai_generation",
  status: "failed",
  progress: 0,
  message: "生成失败",
  error: h.error,
  payload: {},
  result: null,
  created_at: "2026-08-31T14:00:00Z",
  updated_at: "2026-08-31T14:00:01Z",
} as unknown as Job;

describe("任务执行详情宽度", () => {
  it("长 URL 和无空格 JSON 在弹窗内任意断行，不产生横向溢出", () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={client}>
        <JobDetailDialog job={job} onClose={vi.fn()} />
      </QueryClientProvider>,
    );

    const error = screen.getByText(h.error);
    expect(error.className).toContain("[overflow-wrap:anywhere]");
    expect(error.className).toContain("whitespace-pre-wrap");

    const dialog = screen.getByRole("dialog");
    expect(dialog.className).toContain("w-[calc(100vw-2rem)]");
    expect(dialog.className).toContain("min-w-0");
    expect(error.parentElement?.className).toContain("min-w-0");
  });

  it("失败的 LLM 节点直接展示实际返回和解析原因", async () => {
    h.events = [
      {
        id: "event-1",
        job_id: "job-1",
        type: "workflow.node.failed",
        created_at: "2026-08-31T14:00:01Z",
        payload: {
          node_id: "llm",
          name: "整理方案",
          error: "LLM 未返回合法 JSON",
          details: {
            kind: "llm_json_response",
            model: "m",
            response_format: "json_object",
            raw_response: "模型说：稍等，我来整理。",
            parse_error: "Expecting value: line 1 column 1 (char 0)",
          },
        },
      },
    ];

    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={client}>
        <JobDetailDialog job={{ ...job, kind: "workflow" }} onClose={vi.fn()} />
      </QueryClientProvider>,
    );

    expect(await screen.findByText("模型说：稍等，我来整理。")).toBeTruthy();
    expect(screen.getByText("json_object")).toBeTruthy();
    expect(screen.getByText(/Expecting value/)).toBeTruthy();
  });
});


/**
 * 用户报的是「工作流启动后无法中止?」 —— 他正看着这个弹窗里 38% 的进度条。
 *
 * 后端一直能取消(domain/jobs.cancel_job,节点粒度),但界面上**唯一**的入口是任务中心
 * 列表那一行上的 ×。点开详情看进度之后,这里没有任何出口,于是合理的结论就是"停不下来"。
 * 能做的事必须出现在人正看着它的地方。
 */
describe("运行中的任务能在详情里停下", () => {
  function mount(status: string) {
    h.events = [];
    h.cancelled = [];
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    return render(
      <QueryClientProvider client={client}>
        <JobDetailDialog job={{ ...job, kind: "workflow", status } as Job} onClose={vi.fn()} />
      </QueryClientProvider>,
    );
  }

  it("在跑的时候有「取消任务」,点了就真的调用取消", async () => {
    mount("running");
    const button = await screen.findByRole("button", { name: /jobCancel/ });
    fireEvent.click(button);
    await vi.waitFor(() => expect(h.cancelled).toEqual(["job-1"]));
  });

  it("已经结束的不给这个按钮 —— 点了只会得到一句「任务已结束」", () => {
    mount("succeeded");
    expect(screen.queryByRole("button", { name: /jobCancel/ })).toBeNull();
  });
});


describe("任务执行详情:做出了什么", () => {
  //: 点开的是列表里那一行(不带 `result`,见后端 JobSummaryOut);做出了什么由详情接口现取。
  const mountJob = (over: Partial<Job>) => {
    const { result, ...row } = { ...job, status: "succeeded", error: null, ...over } as Job;
    h.full = { ...row, result };
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    return render(
      <QueryClientProvider client={client}>
        <JobDetailDialog job={row as Job} onClose={vi.fn()} />
      </QueryClientProvider>,
    );
  };

  it("画板写字交回的正文摊出来 —— 此前只有状态和一串 job.* 事件", async () => {
    mountJob({ kind: "board_write", result: { text: "林小满,十七岁,班长。" } as Job["result"] });
    const block = await screen.findByText("林小满,十七岁,班长。");
    expect(block.closest("[data-job-result]")).not.toBeNull();
  });

  it("交回的图点开大图,音频就地播,文档格写成的笔记给一条链接", async () => {
    lightbox.openImagePreview.mockClear();
    mountJob({
      kind: "board_run",
      result: { outputs: [
        { type: "asset", asset_id: "img-1" },
        { type: "asset", asset_id: "aud-1" },
        { type: "note", note_id: "note-9", revision: 3, title: "人物小传" },
      ] } as unknown as Job["result"],
    });
    fireEvent.click(await screen.findByRole("button", { name: "三视图" }));
    expect(lightbox.openImagePreview).toHaveBeenCalledWith(expect.objectContaining({ src: "/preview/img-1" }));
    expect(document.querySelector('audio[src="/file/aud-1"]')).not.toBeNull();
    expect(screen.getByText("人物小传").closest("a")).not.toBeNull();
  });

  it("没成功的、交回的东西认不出的(工作流整份上下文)不摆「结果」", async () => {
    mountJob({ kind: "workflow", result: { context: { a: 1 } } as unknown as Job["result"] });
    await screen.findByText("jobDetailEvents");
    expect(document.querySelector("[data-job-result]")).toBeNull();
  });
});

//: 体检 UM-33:执行记录此前直接显示 `job.queued / job.running / job.failed` 和一段原始 JSON;失败的任务不能就地重试。
describe("执行记录说人话,原始数据收进开发者信息", () => {
  function mountWith(events: Array<Record<string, unknown>>, patch: Partial<Job> = {}) {
    h.events = events;
    h.regenerated = [];
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    return render(
      <QueryClientProvider client={client}>
        <JobDetailDialog job={{ ...job, ...patch } as Job} onClose={vi.fn()} />
      </QueryClientProvider>,
    );
  }

  it("认得出的事件写名字;原名和载荷收在「开发者信息」里,默认收着;认不出的照原样", async () => {
    mountWith([
      { id: "e1", type: "job.queued", created_at: "2026-08-31T14:00:00Z", payload: { message: "排上了" } },
      { id: "e2", type: "job.mystery", created_at: "2026-08-31T14:00:01Z", payload: {} },
    ]);
    expect(await screen.findByText("jobEvent_job_queued")).toBeInTheDocument();
    expect(screen.getByText("job.mystery")).toBeInTheDocument();
    const developer = document.querySelector("[data-event-developer]") as HTMLDetailsElement;
    expect(developer.open).toBe(false);
    expect(developer.textContent).toContain("job.queued");
    expect(developer.textContent).toContain("排上了");
  });

  it("失败的预览代理能就地重试;别的种类、没失败的不给", async () => {
    const view = mountWith([], { kind: "proxy", payload: { asset_id: "a1" } as Job["payload"] });
    fireEvent.click(await screen.findByRole("button", { name: /jobRetry/ }));
    await waitFor(() => expect(h.regenerated).toEqual(["a1"]));
    view.unmount();

    const other = mountWith([], { kind: "ai_generation" });
    await screen.findByText("jobDetailEvents");
    expect(screen.queryByRole("button", { name: /jobRetry/ })).toBeNull();
    other.unmount();

    mountWith([], { kind: "proxy", status: "succeeded", error: null, payload: { asset_id: "a1" } as Job["payload"] });
    await screen.findByText("jobDetailEvents");
    expect(screen.queryByRole("button", { name: /jobRetry/ })).toBeNull();
  });
});
