import { api } from "@/api/transport";

/**
 * 官网社区分享的**读**接口(云端 `/api/cloud/v1/shares/*`)。
 *
 * 桌面窗口与官网不同源:云端只接受官网 Origin 的同源反代(见 cloud/app.py 的同一源校验),所以这里
 * 走**本机后端 / 部署后端**的 `/api/cloud/v1` 前缀 —— 生产上由反代转给 Cloud,和官网同一个入口。
 * 路径只写在这里(棘轮 design/apiSeam)。
 *
 * 公开响应里**没有 email、没有 payload**:详情只带标题 / 作者 / 统计,内容单独从 `/payload`
 * 或 `/download` 取;后者顺带把 downloads +1。前端不解析、不信任内容,原样交给后端校验。
 */

/** `cloud_shares.kind`:只有这两种(云端 CheckConstraint)。 */
export type CommunityShareKind = "workflow" | "board";

/** 公开身份三列,没有 email。 */
export type CommunityIdentity = {
  display_name?: string | null;
  handle?: string | null;
  avatar_seed?: string | null;
};

export type CommunityShareStats = {
  downloads: number;
  likes: number;
  favorites: number;
  comments: number;
};

/** `GET /shares/{id}` 的公开形状(不含 payload)。 */
export type CommunityShare = {
  id: string;
  kind: CommunityShareKind;
  title: string;
  summary?: string | null;
  /** 紧凑 UTF-8 JSON 的字节数(云端量的 2 MB 上限就是它)。 */
  bytes?: number;
  license?: string | null;
  created_at?: string;
  author?: CommunityIdentity | null;
  stats?: CommunityShareStats;
  liked_by_me?: boolean;
  favorited_by_me?: boolean;
};

/**
 * 分享 id 只当路径里的**一个**已编码段:云端 id 是短 token,而这里是外部输入面 ——
 * `encodeURIComponent` 之后 `/`、`?`、`#` 都进不了路径。
 */
function sharePath(id: string, suffix = ""): string {
  return `/api/cloud/v1/shares/${encodeURIComponent(id)}${suffix}`;
}

/** 详情:标题、作者、类型、大小、统计。**不含 payload**。 */
export function getCommunityShare(id: string): Promise<CommunityShare> {
  return api<CommunityShare>(sharePath(id));
}

/** 内容本体。预览时先取一次,确认这份分享读得回来;返回的 payload 原样交给后端校验。 */
export function getCommunitySharePayload(id: string): Promise<{ payload: unknown }> {
  return api<{ payload: unknown }>(sharePath(id, "/payload"));
}

/**
 * 下载一次:**downloads +1**,并把内容交出来。
 *
 * 导入时走这一条(而不是再 GET 一次 payload):计进去的那一次下载,和真正被导入的那份内容
 * 是同一次请求 —— 预览 / 取消都不计数。
 */
export function downloadCommunityShare(id: string): Promise<{ payload: unknown }> {
  return api<{ payload: unknown }>(sharePath(id, "/download"), { method: "POST" });
}
