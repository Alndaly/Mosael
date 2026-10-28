// 发布执行器与平台适配器共用的形状。任务的持久化/状态源在 Mosael 后端(/api/publish),publishWorker 把后端任务
// 映射成适配器期望的 PublishTask。不放在 browser/types 里:那份是各块共用的,放进来就让底层回头依赖发布的平台表。
import type { SupportedPlatform } from "./platforms";

export type Platform = SupportedPlatform;

export type TaskStatus =
  | "pending"
  | "running"
  | "waiting_manual"
  | "login_required"
  | "permission_required"
  | "blocked"
  | "cancelled"
  | "success"
  | "failed";

/** 能下发的三种内容形状(ADR 0076);`document` 不是其中一种,它要先转换成这三种之一。 */
export type ContentKind = "video" | "image-text" | "article";

/** 适配器消费的任务形状:contentKind / mediaPaths(视频就是一份)/ title / tags / platformOptions{…}。 */
export interface PublishTask {
  id: string;
  accountId: string;
  accountName: string;
  platform: Platform;
  /** 这一条发的是什么形状(ADR 0076)。必填:没有"没写就当视频"这一档。 */
  contentKind: ContentKind;
  /** 图文 / 文章的全部素材,**按顺序**;视频就是一份。 */
  mediaPaths: string[];
  /** 正文 / 长文(图文与文章用);平台没有正文栏就是空串。 */
  body: string;
  title: string;
  tags: string[];
  platformOptions: Record<string, unknown>;
  scheduledAt: string | null;
  status: TaskStatus;
  errorMessage: string | null;
  screenshotPath: string | null;
  createdAt: string;
  updatedAt: string;
}
