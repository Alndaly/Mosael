// 内嵌浏览器里的下载:**不弹系统保存框,下完直接进素材库。**
//
// 此前视图里点一个下载链接,Chromium 就在 Mosael 窗口上弹系统保存框:人在跟前还好;浏览器自动化里它就一直
// 挂在那儿,动作却报成功,文件不知道去了哪。现在每个视图分区的会话装一个 will-download(只装一次),同步
// 给下载定好临时路径(定了路径就不弹框),再按「谁触发的」分两路交出去:
//
// - **自动化**:那个会话上正有动作在跑(执行器开了收集器,见 collect)—— 这一步触发的下载归这一步,执行器
//   下完交给后端入库(带着哪次运行、哪个节点),素材 id 放进动作结果;
// - **人**:别的一律当用户自己点的 —— 告诉渲染层(进度、下好了、没下成),渲染层用用户的会话把它存进
//   当前工作区,顶栏说一句「已存进素材库」。
//
// 收不收在开始时就判(类型、服务端报的总长,见 downloadRules),下的过程中再按收到的字节数看一遍上限;
// 后端入库时同一道闸再过一次。临时目录在 userData 下(每个实例各一份),交出去之后删,没人认领的十分钟后删。
import { randomUUID } from "node:crypto";
import fs from "node:fs";
import path from "node:path";

import type { DownloadItem, Session, WebContents } from "electron";

import { plog } from "./log";
import {
  MAX_DOWNLOAD_BYTES,
  httpUrlOrEmpty,
  refuseDownload,
  safeDownloadName,
  tooLarge,
  type DownloadRefusal,
} from "./downloadRules";
import { t } from "../i18n.cjs";

/** 下好了、还在临时目录里的一份文件,连同出处。 */
export interface FinishedDownload {
  id: string;
  path: string;
  name: string;
  bytes: number;
  /** 下载地址本身;blob: / data: 这种没有可记的地址时为空。 */
  sourceUrl: string;
  pageUrl: string;
  pageTitle: string;
  startedAt: string;
}

export type CollectedDownload = { ok: true; file: FinishedDownload } | { ok: false; name: string; error: string };

/** 告诉渲染层的那一份(只有「人点的」下载才有)。 */
export interface DownloadNotice {
  id: string;
  name: string;
  state: "progress" | "ready" | "failed";
  receivedBytes: number;
  totalBytes: number;
  /** state = failed 时给人看的那句话(已按界面语言翻好)。 */
  error?: string;
}

/** 没人认领的「人点的」下载留多久。渲染层收到 ready 立刻来取,十分钟还没来就是没人要了。 */
const UNCLAIMED_MS = 10 * 60_000;
/** 进度最多多久报一次。 */
const PROGRESS_EVERY_MS = 500;

const refusalText = (refusal: DownloadRefusal): string => t(refusal.key, refusal.params);

/**
 * 一步自动化动作期间,这个会话里开始的下载。动作跑完,执行器 `settle()`:等一小会儿(点完链接,下载往往
 * 隔一拍才开始),再等已经开始的都下完。
 */
export class DownloadCollector {
  private readonly pending: Promise<CollectedDownload>[] = [];
  private readonly cancels = new Set<() => void>();
  closed = false;

  constructor(private readonly release: () => void) {}

  /** 路由器交来一份刚开始的下载。 */
  add(done: Promise<CollectedDownload>, cancel: () => void): void {
    this.pending.push(done);
    this.cancels.add(cancel);
    void done.finally(() => this.cancels.delete(cancel));
  }

  get count(): number {
    return this.pending.length;
  }

  /**
   * 收尾。`graceMs`:动作做完之后再等多久看有没有下载开始;`stillLoading` 为真(页面还在等主文档的
   * 响应 —— 点的链接可能正要变成一个下载)就多等,最多 `maxLoadingMs`。中止了就把还在下的取消掉。
   * 之后再开始的下载不归这一步(走「人点的」那一路)。
   */
  async settle(opts: {
    graceMs: number;
    signal?: AbortSignal | null;
    stillLoading?: () => boolean;
    maxLoadingMs?: number;
  }): Promise<CollectedDownload[]> {
    const start = Date.now();
    const loadingUntil = start + Math.max(opts.graceMs, opts.maxLoadingMs ?? 8_000);
    const aborted = () => Boolean(opts.signal?.aborted);
    while (!aborted()) {
      const now = Date.now();
      if (now >= start + opts.graceMs && !(opts.stillLoading?.() && now < loadingUntil)) break;
      await new Promise((resolve) => setTimeout(resolve, 100));
    }
    this.closed = true;
    this.release();
    const onAbort = () => {
      for (const cancel of [...this.cancels]) cancel();
    };
    if (aborted()) onAbort();
    else opts.signal?.addEventListener("abort", onAbort, { once: true });
    try {
      return await Promise.all(this.pending);
    } finally {
      opts.signal?.removeEventListener("abort", onAbort);
    }
  }
}

/** 用完了(交出去了,或者不要了):删掉临时文件连同它那一层目录。 */
export function discardDownload(file: FinishedDownload): void {
  fs.rmSync(path.dirname(file.path), { recursive: true, force: true });
}

export class DownloadRouter {
  private readonly watched = new WeakSet<Session>();
  private readonly collectors = new Map<string, DownloadCollector>();
  /** 人点的、已经下好、等渲染层来取的。 */
  private readonly ready = new Map<string, { file: FinishedDownload; timer: ReturnType<typeof setTimeout> }>();

  constructor(
    /** 这个页面属于哪个视图(会话 id / 账号 id);认不出是 null。 */
    private readonly ownerOf: (wc: WebContents) => string | null,
    private readonly notify: (notice: DownloadNotice) => void,
    private readonly root: string,
  ) {
    // 上次没交出去的(崩溃、强退)不留:临时目录只属于这一次运行。
    fs.rmSync(root, { recursive: true, force: true });
  }

  /** 给一个分区的会话装上接管下载的钩子。同一个会话只装一次(分区里的每个页面、弹窗都走它)。 */
  watch(ses: Session): void {
    if (this.watched.has(ses)) return;
    this.watched.add(ses);
    ses.on("will-download", (_event, item, wc) => this.accept(item, wc));
  }

  /** 执行器开始在这个视图上跑一步:这期间开始的下载归它。 */
  collect(viewId: string): DownloadCollector {
    const collector = new DownloadCollector(() => {
      if (this.collectors.get(viewId) === collector) this.collectors.delete(viewId);
    });
    this.collectors.set(viewId, collector);
    return collector;
  }

  /** 渲染层来取一份人点的下载(取走就不再归路由器管,用完由取的人 discardDownload)。 */
  take(id: string): FinishedDownload | null {
    const entry = this.ready.get(id);
    if (!entry) return null;
    clearTimeout(entry.timer);
    this.ready.delete(id);
    return entry.file;
  }


  private accept(item: DownloadItem, wc: WebContents | undefined): void {
    const owner = wc && !wc.isDestroyed() ? this.ownerOf(wc) : null;
    const collector = owner ? this.collectors.get(owner) : undefined;
    const id = randomUUID();
    const name = safeDownloadName(item.getFilename());
    const total = item.getTotalBytes();
    const pageUrl = wc && !wc.isDestroyed() ? httpUrlOrEmpty(wc.getURL()) : "";
    const sourceUrl = httpUrlOrEmpty(item.getURL());
    const base = {
      id,
      name,
      sourceUrl,
      // 新开的会话直接打开一个文件地址时,页面还停在 about:blank:出处的「页面」就记下载地址本身。
      pageUrl: pageUrl || sourceUrl,
      pageTitle: wc && !wc.isDestroyed() ? wc.getTitle().slice(0, 300) : "",
      startedAt: new Date().toISOString(),
    };
    const dir = path.join(this.root, id);
    const target = path.join(dir, name);
    // **同步定好路径**:will-download 返回之前定了路径,Chromium 就不弹保存框。收不了的也先定一个再取消,
    // 免得取消之前那一拍弹出框来。
    fs.mkdirSync(dir, { recursive: true });
    item.setSavePath(target);

    const refusal = refuseDownload(name, total);
    const report = (notice: Omit<DownloadNotice, "id" | "name" | "totalBytes">) => {
      if (!collector) this.notify({ id, name, totalBytes: item.getTotalBytes(), ...notice });
    };
    plog("download started:", owner ?? "(unknown view)", collector ? "automation" : "manual", name);

    const done = new Promise<CollectedDownload>((resolve) => {
      let refused: DownloadRefusal | null = refusal;
      let lastProgress = 0;
      item.on("updated", () => {
        const received = item.getReceivedBytes();
        if (!refused && received > MAX_DOWNLOAD_BYTES) {
          refused = tooLarge();
          item.cancel();
          return;
        }
        const now = Date.now();
        if (now - lastProgress >= PROGRESS_EVERY_MS) {
          lastProgress = now;
          report({ state: "progress", receivedBytes: received });
        }
      });
      item.once("done", (_event, state) => {
        if (state === "completed" && !refused) {
          const bytes = fs.statSync(target, { throwIfNoEntry: false })?.size ?? item.getReceivedBytes();
          plog("download finished:", name, bytes);
          resolve({ ok: true, file: { ...base, path: target, bytes } });
          return;
        }
        fs.rmSync(dir, { recursive: true, force: true });
        const error = refused
          ? refusalText(refused)
          : state === "cancelled"
            ? t("downloadErr_cancelled", { name })
            : t("downloadErr_interrupted", { name });
        plog("download not kept:", name, state, refused?.key ?? "");
        resolve({ ok: false, name, error });
      });
      if (refused) item.cancel();
    });

    if (collector) {
      collector.add(done, () => item.cancel());
      return;
    }
    report({ state: "progress", receivedBytes: 0 });
    void done.then((outcome) => {
      if (!outcome.ok) {
        report({ state: "failed", receivedBytes: item.getReceivedBytes(), error: outcome.error });
        return;
      }
      const timer = setTimeout(() => {
        if (this.ready.delete(id)) discardDownload(outcome.file);
      }, UNCLAIMED_MS);
      timer.unref?.();
      this.ready.set(id, { file: outcome.file, timer });
      report({ state: "ready", receivedBytes: outcome.file.bytes });
    });
  }
}
