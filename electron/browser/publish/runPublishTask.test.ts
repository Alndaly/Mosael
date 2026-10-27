import { mkdtemp, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import path from "node:path";

import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("electron", () => ({ app: { getPath: () => "/tmp" } }));

const { runPublishTask } = await import("./runPublishTask");
type RunPublishTask = typeof runPublishTask;
type Options = Parameters<RunPublishTask>[1];
type BackendTask = Parameters<RunPublishTask>[0];

function task(mediaPaths: string[]): BackendTask {
  return {
    id: "task-1",
    account_id: "account-1",
    account_name: "账号",
    platform: "mock",
    proxy: null,
    content_kind: "video",
    body: "",
    media_paths: mediaPaths,
    title: "标题",
    tags: ["标签"],
    description: "",
    short_title: "",
    options: {},
    status: "running",
  };
}

function harness() {
  const calls: string[] = [];
  const adapter = {
    supports: ["video"],
    openCreatorPage: vi.fn(async () => { calls.push("open"); }),
    checkLogin: vi.fn(async () => { calls.push("login"); return true; }),
    uploadVideo: vi.fn(async () => { calls.push("upload"); }),
    fillTitle: vi.fn(async () => { calls.push("title"); }),
    fillTags: vi.fn(async () => { calls.push("tags"); }),
    submit: vi.fn(async () => { calls.push("submit"); }),
    waitResult: vi.fn(async () => { calls.push("result"); }),
    knownPostId: () => null,
  };
  const backend = {
    taskStatus: vi.fn(async () => ({ status: "running" })),
    patchAccount: vi.fn(async () => undefined),
    reportTask: vi.fn(async () => undefined),
  };
  const views = {
    setAccountPlatform: vi.fn(),
    panelAttach: vi.fn(),
    isPanelled: () => true,
    configureAccount: vi.fn(async () => undefined),
    panelDetach: vi.fn(),
  };
  const driver = {
    setAbortSignal: vi.fn(),
    url: () => "https://example.test/publish",
    setMetricsOverride: vi.fn(async () => undefined),
    clearMetricsOverride: vi.fn(async () => undefined),
    screenshot: vi.fn(async () => undefined),
    evaluate: vi.fn(async () => ({
      url: "https://example.test/publish",
      title: "发布",
      text: "",
      fileAccepts: [],
      candidates: [],
    })),
    captureResponses: vi.fn(() => null),
  };
  const mirror = { start: vi.fn(), step: vi.fn() };
  const options = {
    views,
    driver,
    mirror,
    controller: new AbortController(),
    trace: { event: vi.fn() },
    isStopped: () => false,
    onSettled: vi.fn(),
    requestFront: vi.fn(),
    backend,
    createAdapter: () => adapter,
    delay: async () => undefined,
    stepDelay: () => 0,
  } as unknown as Options;
  return { calls, adapter, backend, views, driver, mirror, options };
}

describe("runPublishTask", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("按单任务状态机完成上传、填表、提交并回报成功", async () => {
    const media = path.join(await mkdtemp(path.join(tmpdir(), "publish-task-")), "video.mp4");
    await writeFile(media, "video");
    const h = harness();

    await runPublishTask(task([media]), h.options);

    expect(h.calls).toEqual(["open", "login", "upload", "title", "tags", "submit", "result"]);
    expect(h.backend.reportTask).toHaveBeenCalledWith("task-1", { status: "success", post: null });
    expect(h.options.onSettled).toHaveBeenCalledWith(expect.objectContaining({ id: "task-1" }), "success");
    expect(h.views.panelDetach).toHaveBeenCalledWith("account-1");
    expect(h.driver.clearMetricsOverride).toHaveBeenCalled();
  });

  it("素材缺失时在动手前失败，回报失败且不调用上传", async () => {
    const h = harness();

    await runPublishTask(task(["/definitely/missing.mp4"]), h.options);

    expect(h.calls).toEqual(["open", "login"]);
    expect(h.adapter.uploadVideo).not.toHaveBeenCalled();
    expect(h.backend.reportTask).toHaveBeenCalledWith(
      "task-1",
      expect.objectContaining({ status: "failed", screenshot_path: expect.any(String) }),
    );
    expect(h.options.onSettled).toHaveBeenCalledWith(expect.objectContaining({ id: "task-1" }), "failed");
    expect(h.views.panelDetach).toHaveBeenCalledWith("account-1");
  });

  it("停止中的任务不再回报为失败", async () => {
    const h = harness();
    h.options.isStopped = () => true;
    h.adapter.openCreatorPage.mockRejectedValueOnce(new Error("stopped"));

    await runPublishTask(task([]), h.options);

    expect(h.backend.reportTask).not.toHaveBeenCalled();
    expect(h.options.onSettled).toHaveBeenCalledWith(expect.objectContaining({ id: "task-1" }), "cancelled");
  });
});
