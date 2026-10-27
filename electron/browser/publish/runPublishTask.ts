import { app } from "electron";
import { mkdir, stat as fsStat } from "node:fs/promises";
import path from "node:path";

import { t as tr } from "../../i18n.cjs";
import type { AccountViewManager } from "../pool/accountViews";
import { createAdapter as defaultCreateAdapter } from "./adapters";
import { clickTextPreferTrusted, publishError, type PublishAdapter } from "./adapters/shared";
import { contractFor } from "./platformContracts";
import { isAutomationBlockedError } from "../errors";
import { plog } from "../log";
import { clearOverlays } from "./overlays";
import type { PageDriver } from "../page/pageDriver";
import { platformName, resolvePlatform } from "./platforms";
import { findPost, postEndpoint } from "./publishedPost";
import * as defaultBackend from "./publishBackend";
import type { ContentKind, PublishTask } from "../types";

const BACKGROUND_VIEWPORT = { width: 1280, height: 800 };
export interface PublishTaskTrace {
  event(type: string, payload?: unknown): void;
}

export interface PublishTaskMirror {
  start(): void;
  step(label: string, settled?: boolean): void;
}

export interface RunPublishTaskOptions {
  views: AccountViewManager;
  driver: PageDriver;
  mirror: PublishTaskMirror;
  controller: AbortController;
  trace: PublishTaskTrace;
  isStopped: () => boolean;
  onSettled: (task: PublishTask, status: string) => void;
  requestFront: (accountId: string) => void;
  backend?: typeof defaultBackend;
  createAdapter?: typeof defaultCreateAdapter;
  delay?: (ms: number) => Promise<void>;
  stepDelay?: () => number;
}

const UPLOAD_BY_KIND: Partial<Record<ContentKind, (adapter: PublishAdapter, task: PublishTask) => Promise<void>>> = {
  video: (adapter, task) => adapter.uploadVideo(task.mediaPaths[0]),
  "image-text": (adapter, task) => {
    if (!adapter.uploadImages) {
      return Promise.reject(publishError(task.platform, "publishErr_kindNotImplemented", { kind: "image-text" }));
    }
    return adapter.uploadImages(task.mediaPaths);
  },
  article: (adapter, task) => adapter.uploadCover?.(task.mediaPaths) ?? Promise.resolve(),
};

const FILLS_BODY: Partial<Record<ContentKind, true>> = { "image-text": true, article: true };

function toAdapterTask(t: defaultBackend.BackendTask): PublishTask {
  return {
    id: t.id,
    accountId: t.account_id,
    accountName: t.account_name,
    platform: resolvePlatform(t.platform).id,
    contentKind: (t.content_kind as ContentKind | undefined) ?? "video",
    mediaPaths: t.media_paths,
    body: t.body ?? "",
    title: t.title,
    tags: t.tags || [],
    platformOptions: {
      ...t.options,
      description: t.description || "",
      shortTitle: t.short_title || "",
    },
    scheduledAt: null,
    status: "running",
    errorMessage: null,
    screenshotPath: null,
    createdAt: "",
    updatedAt: "",
  };
}

async function captureFailure(taskId: string, driver: PageDriver): Promise<string | null> {
  try {
    const dir = path.join(app.getPath("userData"), "publish-screenshots");
    await mkdir(dir, { recursive: true });
    const file = path.join(dir, `${taskId}-${Date.now()}.png`);
    await driver.screenshot(file);
    return file;
  } catch {
    return null;
  }
}

async function collectFailureForensics(
  task: PublishTask,
  driver: PageDriver,
  trace: PublishTaskTrace,
  error: unknown,
  stepLabel: string,
): Promise<void> {
  try {
    const facts = await driver.evaluate<{
      url: string;
      title: string;
      text: string;
      fileAccepts: string[];
      candidates: { tag: string; text: string; x: number; y: number }[];
    }>(`(() => {
      const visible = (e) => {
        const r = e.getBoundingClientRect();
        return r.width > 0 && r.height > 0 && r.right > 0 && r.bottom > 0 && r.left < innerWidth && r.top < innerHeight;
      };
      const candidates = [...document.querySelectorAll("button, [role=button], a, .creator-tab, input, [contenteditable]")]
        .filter(visible)
        .slice(0, 40)
        .map((e) => ({
          tag: e.tagName.toLowerCase(),
          text: (e.textContent || e.getAttribute("placeholder") || "").trim().slice(0, 40),
          x: Math.round(e.getBoundingClientRect().x),
          y: Math.round(e.getBoundingClientRect().y),
        }))
        .filter((one) => one.text);
      return {
        url: location.href,
        title: document.title,
        text: (document.body?.innerText || "").slice(0, 2000),
        fileAccepts: [...document.querySelectorAll('input[type="file"]')].map((one) => one.getAttribute("accept") || ""),
        candidates: candidates.slice(0, 12),
      };
    })()`);
    trace.event("publish-failure", {
      task: task.id,
      platform: task.platform,
      kind: task.contentKind,
      step: stepLabel,
      error: (error instanceof Error ? error.message : String(error)).slice(0, 300),
      ...facts,
    });
    plog("publish forensics:", task.id, stepLabel, facts.url.slice(0, 120), `candidates=${facts.candidates.length}`);
  } catch (failure) {
    plog("publish forensics failed:", task.id, String(failure).slice(0, 160));
  }
}

async function firstMissingMedia(task: PublishTask): Promise<string | null> {
  for (const [index, file] of task.mediaPaths.entries()) {
    try {
      const stat = await fsStat(file);
      if (!stat.isFile() || stat.size === 0) return mediaName(task, index, file);
    } catch {
      return mediaName(task, index, file);
    }
  }
  return null;
}

function mediaName(task: PublishTask, index: number, file: string): string {
  const base = path.basename(file);
  if (task.mediaPaths.length <= 1) return base;
  return `${index + 1}/${task.mediaPaths.length} · ${base}`;
}

function resolveBlockedStatus(
  error: unknown,
): "waiting_manual" | "login_required" | "permission_required" | "blocked" | null {
  if (!isAutomationBlockedError(error)) return null;
  if (error.reason === "manual_required") return "waiting_manual";
  if (error.reason === "login_required") return "login_required";
  if (error.reason === "permission_required") return "permission_required";
  return "blocked";
}

/** 执行一条发布任务。worker 只负责认领、并发与视图生命周期；这里拥有单任务的完整状态机。 */
export async function runPublishTask(bt: defaultBackend.BackendTask, options: RunPublishTaskOptions): Promise<void> {
  const {
    views: taskViews,
    driver,
    mirror,
    controller,
    trace,
    isStopped,
    onSettled,
    requestFront,
    backend = defaultBackend,
    createAdapter = defaultCreateAdapter,
    delay = (ms) => new Promise<void>((resolve) => setTimeout(resolve, ms)),
    stepDelay = () => 700 + Math.floor(Math.random() * 1100),
  } = options;
  const t = toAdapterTask(bt);
  plog("runTask start:", bt.id, bt.platform, bt.media_paths.join(", "));
  taskViews.setAccountPlatform?.(bt.account_id, bt.platform);
  const platformLabel = platformName(t.platform);
  driver.setAbortSignal(controller.signal);
  let cancelled = false;
  const checkpoint = async (): Promise<void> => {
    controller.signal.throwIfAborted();
    try {
      const state = await backend.taskStatus(t.id);
      if (state.status !== "running") {
        cancelled = true;
        controller.abort(new Error("Task is no longer running"));
      }
    } catch (error) {
      controller.abort(error);
    }
    controller.signal.throwIfAborted();
  };
  let polling = false;
  let capture: { stop(): Promise<unknown> } | null = null;
  const cancellationTimer = setInterval(() => {
    if (polling || controller.signal.aborted) return;
    polling = true;
    void checkpoint().catch(() => undefined).finally(() => { polling = false; });
  }, 500);
  let stepLabel = "";
  const contract = contractFor(t.platform);
  const clearStuckOverlays = async (): Promise<void> => {
    if (!contract.overlays.length) return;
    await clearOverlays(driver, contract.overlays, resolvePlatform(t.platform).id, (text) =>
      clickTextPreferTrusted(driver, text, { exact: true, selector: "button, [role=button], div, span" }),
    ).catch((error: unknown) => plog("clearStuckOverlays failed:", String(error).slice(0, 120)));
  };
  const step = async (label: string, settled = false): Promise<void> => {
    await checkpoint();
    stepLabel = label;
    plog("runTask step:", bt.id, label);
    mirror.step(`${platformLabel} · ${label}`, settled);
    if (!settled) await clearStuckOverlays();
  };
  try {
    await checkpoint();
    taskViews.panelAttach(t.accountId);
    if (!taskViews.isPanelled(t.accountId)) {
      await driver.setMetricsOverride(BACKGROUND_VIEWPORT.width, BACKGROUND_VIEWPORT.height);
    }
    mirror.start();
    await taskViews.configureAccount(t.accountId, bt.proxy);
    const adapter = createAdapter(t.platform, driver, t);
    await step(tr("publishStep_openCreator"));
    await adapter.openCreatorPage();
    plog("runTask creator page opened:", bt.id, driver.url());
    await delay(stepDelay());

    await step(tr("publishStep_checkLogin"));
    const loggedIn = await adapter.checkLogin();
    plog("runTask checkLogin:", bt.id, loggedIn);
    if (!loggedIn) {
      await backend.patchAccount(t.accountId, {
        binding_status: "login_required",
        last_error: tr("publishErr_notLoggedIn"),
      });
      await backend.reportTask(t.id, { status: "login_required", error_message: tr("publishErr_notLoggedInTask") });
      onSettled(t, "login_required");
      return;
    }
    await backend.patchAccount(t.accountId, { binding_status: "bound", last_error: null });

    await step(tr("publishStep_upload"));
    const kind = t.contentKind;
    const supported = adapter.supports;
    const upload = UPLOAD_BY_KIND[kind];
    if (!supported.includes(kind) || !upload) {
      throw publishError(t.platform, "publishErr_kindNotImplemented", { kind });
    }
    const missing = await firstMissingMedia(t);
    if (missing) throw publishError(t.platform, "publishErr_assetFileMissing", { name: missing });
    await upload(adapter, t);
    await delay(stepDelay());
    await step(tr("publishStep_fillTitle"));
    await adapter.fillTitle(t.title);
    await delay(stepDelay());
    if (FILLS_BODY[kind] && t.body) {
      const fillBody = adapter.fillBody?.bind(adapter);
      if (!fillBody) throw publishError(t.platform, "publishErr_kindNotImplemented", { kind });
      await step(tr("publishStep_fillBody"));
      await fillBody(t.body);
      await delay(stepDelay());
    }
    await step(tr("publishStep_fillTags"));
    await adapter.fillTags(t.tags);
    await delay(stepDelay());

    const endpoint = postEndpoint(resolvePlatform(t.platform).id);
    const listening = endpoint ? driver.captureResponses(endpoint) : null;
    capture = listening;
    await step(tr("publishStep_submit"));
    await adapter.submit();
    await delay(stepDelay());
    await step(tr("publishStep_waitConfirm"));
    await adapter.waitResult();
    const responses = listening ? await listening.stop() : [];
    capture = null;
    const post = findPost(resolvePlatform(t.platform).id, responses, adapter.knownPostId?.() ?? null);
    plog("runTask post:", t.id, { responses: responses.map((r) => r.url), post });
    await step(tr("publishStep_done"), true);
    await backend.reportTask(t.id, { status: "success", post });
    plog("runTask success:", t.id);
    onSettled(t, "success");
  } catch (error) {
    if (cancelled || isStopped()) {
      onSettled(t, "cancelled");
      return;
    }
    const message = error instanceof Error ? error.message : String(error);
    plog("runTask error:", t.id, error instanceof Error ? error : message);
    mirror.step(`${platformLabel} · ${tr("publishStep_failed")}`, true);
    const screenshot = await captureFailure(t.id, driver);
    await collectFailureForensics(t, driver, trace, error, stepLabel);
    const blocked = resolveBlockedStatus(error);
    const bindingStatus =
      blocked === "login_required"
        ? "login_required"
        : blocked === "waiting_manual"
          ? "manual_required"
          : blocked === "permission_required"
            ? "permission_required"
            : null;
    if (bindingStatus) {
      await backend
        .patchAccount(t.accountId, { binding_status: bindingStatus, last_error: message })
        .catch((patchError: unknown) =>
          plog("runTask patchAccount failed (still reporting):", t.id, String(patchError).slice(0, 120)),
        );
    }
    await backend.reportTask(t.id, { status: blocked ?? "failed", error_message: message, screenshot_path: screenshot });
    onSettled(t, blocked ?? "failed");
    if (bindingStatus) requestFront(t.accountId);
  } finally {
    clearInterval(cancellationTimer);
    await capture?.stop().catch(() => undefined);
    taskViews.panelDetach(t.accountId);
    await driver.clearMetricsOverride().catch(() => undefined);
  }
}
