// 自动化动作里触发的下载:动作做完,收齐这一步开始的下载,交给后端入库,素材 id 放进动作结果。
//
// 收不进素材库的(类型不收、超过上限、下到一半断了、后端拒了)让这一步**失败并说清为什么** —— 此前
// 浏览器弹出保存框挂在那儿,动作却报成功,工作流的下一步拿着一个不存在的文件接着跑。
import fs from "node:fs";

import { browserBackend } from "./browserBackend";
import { UploadRefused, provenanceFields } from "./downloadUpload";
import { discardDownload, type DownloadCollector } from "./downloads";
import { t } from "../i18n.cjs";

/**
 * 点击之后再等多久看有没有下载开始。点下载链接到浏览器认出「这是个下载」要等服务端回响应头:本机
 * 几毫秒,远处的 CDN 几百毫秒。页面还在等主文档响应时另外接着等(见 DownloadCollector.settle)。
 */
export const CLICK_DOWNLOAD_GRACE_MS = 600;

export interface SavedDownload {
  asset_id: string;
  name: string;
  bytes: number;
}

/** 动作失败了:这一步开始的下载一并取消、删掉,不进素材库(失败的那一步不该留下东西)。 */
export async function dropActionDownloads(collector: DownloadCollector): Promise<void> {
  const collected = await collector.settle({ graceMs: 0, signal: AbortSignal.abort() });
  for (const one of collected) if (one.ok) discardDownload(one.file);
}

/**
 * 动作成功了:收齐这一步的下载并入库。有一份没进素材库就抛出那句人话(已经入库的照样留着,结果里也有)。
 */
export async function saveActionDownloads(opts: {
  actionId: string;
  action: string;
  collector: DownloadCollector;
  signal: AbortSignal;
  stillLoading: () => boolean;
}): Promise<SavedDownload[]> {
  const collected = await opts.collector.settle({
    graceMs: opts.action === "click" ? CLICK_DOWNLOAD_GRACE_MS : 0,
    signal: opts.signal,
    stillLoading: opts.stillLoading,
  });
  const saved: SavedDownload[] = [];
  const problems: string[] = [];
  for (const one of collected) {
    if (!one.ok) {
      problems.push(one.error);
      continue;
    }
    try {
      const asset = await browserBackend.uploadArtifact(
        opts.actionId,
        "download",
        { body: await fs.openAsBlob(one.file.path), filename: one.file.name },
        provenanceFields(one.file),
      );
      saved.push({ asset_id: asset.asset_id, name: asset.name, bytes: one.file.bytes });
    } catch (error) {
      const reason = error instanceof UploadRefused ? error.message : error instanceof Error ? error.message : String(error);
      problems.push(t("downloadErr_saveFailed", { name: one.file.name, reason }));
    } finally {
      discardDownload(one.file);
    }
  }
  if (problems.length) throw new Error(problems.join(";"));
  return saved;
}
