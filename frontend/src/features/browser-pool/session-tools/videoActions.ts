/**
 * 下载页面里的视频:走哪条路、交给后端什么(主进程那一半在 electron/publish/pageVideos)。
 */
import { importFromUrl, type Job } from "@/api/client";

import type { PageInfo, PageToolsBridge } from "./pageActions";

export type VideoProbe = Awaited<ReturnType<PageToolsBridge["probeVideos"]>>;
export type VideoCandidate = VideoProbe["candidates"][number];

/**
 * 下载页面里的视频:排一次「从链接导入」任务(后台跑、有进度、能取消,完成进素材库)。
 *
 * - 平台页面(B 站 / 抖音 / 小红书 / YouTube…,yt-dlp 有站点解析器的)交页面地址 —— 解析器知道怎么取流;
 * - 页面里找到的直链 / HLS 交那条地址,并带上所在页面(后端记出处、下载时当 Referer)。
 *
 * 两种都借当前档案的登录态(profile_id):后端经执行器从这个档案的分区里取 cookie,写成临时 cookies.txt
 * 交给 yt-dlp,不进日志、用完即删(见 backend domain/assets/from_url._cookie_file)。
 */
export function startVideoDownload(params: {
  workspaceId: string;
  page: PageInfo;
  profileId: string | null;
  /** 不给 = 按整页(平台页面)下载。 */
  candidate?: VideoCandidate;
}): Promise<Job> {
  const { page, candidate } = params;
  return importFromUrl({
    workspace_id: params.workspaceId,
    items: [{ url: candidate ? candidate.url : page.url, title: page.title, page_url: page.url, page_title: page.title }],
    kind: "video",
    max_height: 0,
    profile_id: params.profileId,
  });
}

/** 这个候选能不能下:受保护的(DRM / 加密流)不能,界面如实说。 */
export function downloadable(candidate: VideoCandidate): boolean {
  return candidate.protection === null;
}

/** 下载任务的第一份产出(从链接导入的任务把入库的素材记在 result.asset_ids 里)。 */
export function jobAssetId(job: Job): string | null {
  const ids = (job.result as { asset_ids?: unknown } | null | undefined)?.asset_ids;
  return Array.isArray(ids) && typeof ids[0] === "string" ? ids[0] : null;
}
