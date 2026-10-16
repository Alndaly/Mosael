import type { components } from "@/api/generated/schema";
import type { Job } from "@/api/domains/jobs";
import { API_BASE, api, getAuthToken } from "@/api/transport";

/**
 * 拆镜头(ADR 0061 §5):排任务、读这份视频的镜头表、取逐镜的帧图。
 *
 * 后端那三条路在 `backend/app/api/routes/shots.py`;领域逻辑在 `domain/shots`。**没拆过不是 404** ——
 * 「这条视频还没拆过」是一次正常的回答(`status: "none"`),界面据此决定显示按钮还是那一列镜头。
 */

/** `GET /assets/{id}/shots` 的回答。没拆过时只有 `asset_id` 和 `status`。 */
export type ShotBreakdown = components["schemas"]["ShotBreakdownResponse"];

/**
 * `GET /assets/{id}/shots/track` 的回答:**整条**动静曲线(5Hz 的每个采样)。
 *
 * 时间轴**不是** `i / hz`:`values[i]` 在 `first_sample_seconds + i × sample_interval_seconds` 秒,
 * 第 0 个采样不在 0 秒(ffmpeg 的 `tblend` 第 0 帧没有前一帧)。两个数都从响应里读。
 *
 * `status` 三种,**没有一种是 404**:`ready` 有曲线;`none` 没量过(或这一版之前的行没记);
 * `missing` 库里记着 `points` 与 `digest`、盘上那份丢了或被改过 —— 这时 `values` 是空的。
 */
export type ShotMotionTrack = components["schemas"]["ShotMotionTrackResponse"];

/** 拆镜头任务的那一种(后端 `domain/analysis/shots_task.JOB_KIND`)。按它列任务就能查「这条视频还在拆吗」。 */
export const SHOT_JOB_KIND = "shot_breakdown";

/**
 * 逐镜。
 *
 * **上半截每一镜都有**(代码量的):镜号、起止、时长、实测动静、台词。下半截**判过画面才有** ——
 * 没有视觉模型时 `size` / `camera` / `frame` / `prompt` 这些键**一个都不在**(不是空串,是根本没有),
 * 所以它们全是可选的。界面按「键在不在」区分「没判过」和「判了但没写」。
 *
 * 封闭词表:`size` / `category` / `camera[]` / `transition_in` / `rhythm` 的取值见 `domain/shots/vocab.py`,
 * 界面的标签在 `features/media/shotVocab.ts`。
 */
export interface Shot {
  /** `S01`、`S02`…… */
  id: string;
  start: number;
  end: number;
  seconds: number;
  /** 实测动静(镜内帧间差的中位数,0–255)。 */
  motion: number;
  /** 按时间重叠从逐字稿分到这一镜的台词(代码分的)。 */
  dialogue?: string;
  /** 景别。 */
  size?: string;
  category?: string;
  /** 运镜,至多两个。 */
  camera?: string[];
  transition_in?: string;
  rhythm?: string;
  rhythm_note?: string;
  subjects?: string[];
  onscreen_text?: string;
  audio?: string;
  /** 画面描述(模型写)。 */
  frame?: string;
  /** 分镜提示词(模型写)。 */
  prompt?: string;
  note?: string;
}

/** 对账 / 节奏的一条提示:`kind` 见 `domain/shots/describe.py`,界面按它翻成一句话。 */
export interface ShotHint {
  /** 哪一镜(开篇没钩子这类整片提示是空串)。 */
  shot?: string;
  kind?: string;
  /** 说的是哪一格(`size` / `camera` / `rhythm`……)。 */
  field?: string;
  /** 相关的值(被清掉的词、实测动静、批的最后一镜……)。 */
  value?: string;
}

/** 谁判的画面、判了几批、出了什么错(一镜都没判过时是空的,或者只有 `error`)。 */
export interface ShotDescribe {
  provider?: string;
  model?: string;
  batches?: number;
  judged_batches?: number;
  /** 没判的原因(后端已经翻成一句人话:没有视觉模型、钥匙没配……)。 */
  error?: string;
}

/** 逐镜那份 JSON 的类型收口 —— **只有这一处**把后端的裸 dict 读成 `Shot`。 */
export function shotsOf(breakdown: Pick<ShotBreakdown, "shots">): Shot[] {
  return (breakdown.shots ?? []) as unknown as Shot[];
}

export function hintsOf(breakdown: Pick<ShotBreakdown, "hints">): ShotHint[] {
  return (breakdown.hints ?? []) as unknown as ShotHint[];
}

export function describeOf(breakdown: Pick<ShotBreakdown, "describe">): ShotDescribe {
  return (breakdown.describe ?? {}) as ShotDescribe;
}

/**
 * 这份视频的镜头表。**没拆过也是 200**(`status: "none"`),不是 404。
 *
 * 它挂在 `assets` 前缀下(`queryKeys.shotKeys.detail`):拆镜头任务做完时任务中心按目录里的
 * `affects: assets` 整片作废,这一份跟着刷。
 */
export function getShotBreakdown(assetId: string): Promise<ShotBreakdown> {
  return api<ShotBreakdown>(`/api/assets/${encodeURIComponent(assetId)}/shots`);
}

/**
 * 这份视频的**整条动静曲线**(节奏条画的就是它)。
 *
 * 和镜头表同一族(挂在 `assets` 前缀下),曲线本身不在镜头表里 —— 1 小时 ≈ 18000 个数,读一次镜头表
 * 不该把它整个搬过来(后端 `ShotMotionTrackResponse` 的说明)。
 */
export function getShotMotionTrack(assetId: string): Promise<ShotMotionTrack> {
  return api<ShotMotionTrack>(`/api/assets/${encodeURIComponent(assetId)}/shots/track`);
}

/**
 * 排一条「拆镜头」后台任务(几秒到几十秒;配了视觉模型还会逐批判画面)。
 *
 * **重拆覆盖同一张表** —— 一份素材一份(ADR 0061 待拍板 2),没有历史版本。返回的是那条任务,
 * 进度去任务中心看(`GET /api/jobs/{id}`、列表按 `kind=shot_breakdown`)。
 */
export function startShotBreakdown(assetId: string): Promise<Job> {
  return api<Job>(`/api/assets/${encodeURIComponent(assetId)}/shots`, { method: "POST" });
}

/**
 * 某一镜那一帧的图(15% 处是 `S03a.jpg`,85% 处是 `S03b.jpg`)。
 *
 * 帧是这张表的插图,不进素材库;名字不在这个形状里(或者那一镜没取到帧)都是 404。
 * 和素材自己的 `/file`、`/thumbnail` 一样带 `?token=`:它给 `<img src>` 用,发不出 Authorization 头。
 */
export function shotFrameUrl(assetId: string, name: string): string {
  const token = getAuthToken();
  const suffix = token ? `?token=${token}` : "";
  return `${API_BASE}/api/assets/${encodeURIComponent(assetId)}/shots/frames/${encodeURIComponent(name)}${suffix}`;
}
