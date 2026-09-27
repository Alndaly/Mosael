/**
 * 社区服务(ADR 0026)的响应形状。
 *
 * ADR 只钉了路径、分页、错误与登录回包;条目、会话、审核队列这些字段名对齐的是社区服务的实现
 * (`community/src/community/api/views.py` 与各路由)。服务改了形状,改这里一处,类型检查会把用到的
 * 地方全指出来。
 */

export type Role = "user" | "moderator" | "admin";

/** 公开可见的那部分:作者署名、主页。 */
export type PublicUser = {
  handle: string;
  display_name: string;
  avatar_url: string | null;
  /** `official` 这个作者(官方条目迁到它名下,ADR 0026 §4)。 */
  official?: boolean;
  created_at?: string | null;
};

/** `GET /me` 与登录回包里的 `user`。 */
export type User = PublicUser & {
  id: string;
  role: Role;
  status?: string;
  /** 打了码的手机号。没绑定时为 null。 */
  phone?: string | null;
  has_password?: boolean;
  /** handle 只能改一次(ADR「我」一节):改过之后为 false。 */
  handle_changeable?: boolean;
  terms_version?: string | null;
};

/** 「登录」的回包:网页的刷新令牌只在 Set-Cookie 里,这里没有。 */
export type LoginResponse = {
  access_token: string;
  /** 秒。 */
  expires_in: number;
  user: User;
};

/** 统一错误体:`{"error": {"code", "message"}}`,message 已按 Accept-Language 给好。 */
export type ErrorBody = { error: { code: string; message: string } };

/** 列表一律游标分页。 */
export type Page<T> = { items: T[]; next_cursor: string | null };

export type ItemKind = "workflow" | "plugin";
export type SortKey = "trending" | "new" | "downloads";
export const SORT_KEYS: readonly SortKey[] = ["trending", "new", "downloads"];

/** 按天计数(下载走势、贡献热力图)。date 是 `YYYY-MM-DD`。 */
export type DailyCount = { date: string; count: number };

/** 列表里的一项。工作流、插件共用这一截。 */
export type ItemSummary = {
  kind: ItemKind;
  slug: string;
  title: string;
  /** 一句话简介。官方条目迁过来的带行内 markdown,经 InlineMarkdown / toPlainText 上页面。 */
  summary: string;
  tags: string[];
  cover_url: string | null;
  official: boolean;
  author: PublicUser;
  /** 当前公开的版本号;还没有公开的版本(插件在审核中)时为 null。 */
  version: string | null;
  downloads: number;
  likes: number;
  views?: number;
  created_at: string;
  updated_at: string;
};

export type WorkflowSummary = ItemSummary & {
  node_count: number;
  /** 含「运行代码」节点:详情页要醒目标出(ADR §4)。 */
  has_code: boolean;
};

export type PluginSummary = ItemSummary & {
  /** 清单里的反写域名 id(和应用里「从文件安装」的是同一个)。 */
  plugin_id: string;
  /** 清单的运行方式:`mcp` 连一个 MCP 服务,其余是本地进程。 */
  runtime: string;
  permissions: string[];
};

export type WorkflowNode = {
  id: string;
  type: string;
  name?: string;
  position?: { x: number; y: number };
};
export type WorkflowEdge = { id?: string; source: string; target: string };
export type WorkflowGraph = { nodes: WorkflowNode[]; edges: WorkflowEdge[]; meta?: { template_id?: string } };

export type SubmissionStatus = "pending" | "approved" | "rejected";

/** `GET /{kind}s/{slug}/versions` 的一项;作者本人看得到审核状态。 */
export type ItemVersion = {
  id: string;
  number: number;
  version: string;
  created_at: string;
  changelog?: string | null;
  size?: number | null;
  sha256?: string | null;
  status?: SubmissionStatus;
  review_note?: string | null;
  reviewed_at?: string | null;
};

type DetailExtras = {
  /** 较长的说明,markdown。**用户写的**:只经 SafeMarkdown 渲染,不进 MDX。 */
  description?: string | null;
  current_version?: ItemVersion | null;
  versions_count?: number;
  /** 登录后才有意义;匿名请求时是 null。 */
  liked?: boolean | null;
  /** 近 30 天逐日下载(ADR §7 的走势线)。 */
  downloads_30d?: DailyCount[];
};

export type WorkflowDetail = WorkflowSummary &
  DetailExtras & {
    /** 当前版本工作流文件里的 `graph`,给详情页画节点图。 */
    graph?: WorkflowGraph | null;
    extra?: { requires?: string[]; stages?: string[] };
  };

export type PluginDetail = PluginSummary &
  DetailExtras & {
    extra?: {
      permissions?: string[];
      runtime?: string;
      tools?: { name: string; description?: string }[];
      credentials?: string[];
      homepage?: string | null;
    };
  };

/** `GET /me/submissions`:我提交过的每一个版本。 */
export type Submission = ItemVersion & {
  kind: ItemKind;
  slug: string;
  title: string;
  path: string;
  hidden: boolean;
};

/** `GET /me/sessions`。 */
export type SessionInfo = {
  id: string;
  /** `web` 或 `device`(设备授权的桌面应用)。 */
  kind?: string;
  device_name: string | null;
  ip: string | null;
  user_agent: string | null;
  created_at: string;
  last_used_at: string;
  /** 就是发这个请求的会话:撤销它等于退出。 */
  current?: boolean;
};

export type Visibility = "unlisted" | "public";

/** `GET /me/shares`、`GET /shares`、作者主页里的一项。 */
export type ShareSummary = {
  slug: string;
  title: string;
  visibility: Visibility;
  version: number | null;
  item_count?: number;
  url?: string;
  cover_url?: string | null;
  og_image_url?: string | null;
  owner?: PublicUser;
  hidden?: boolean;
  created_at?: string;
  updated_at: string;
};

export type SnapshotMedia = {
  sha256: string;
  content_type: string;
  width?: number;
  height?: number;
  thumb_sha256?: string;
};

export type SnapshotItemKind = "note" | "image" | "video" | "audio" | "frame" | "scene" | "document" | "entity";

/** `mosael.board-snapshot/1` 里的一格:与本机画布的格子同形,去掉运行态。 */
export type SnapshotItem = {
  id: string;
  kind: SnapshotItemKind | (string & {});
  x: number;
  y: number;
  width?: number;
  height?: number;
  title?: string;
  text?: string;
  color?: string;
  media?: SnapshotMedia;
  /** 3D 场景格的预览图。 */
  preview?: SnapshotMedia;
  /** 资产格(ADR 0027)引用的是人物、场景还是道具:`character` / `location` / `prop`。封面在 `media`。 */
  entity_kind?: string;
  markdown?: string;
  revision?: number;
};

export type BoardSnapshot = {
  schema: "mosael.board-snapshot/1";
  viewport?: { x: number; y: number; zoom: number };
  items: SnapshotItem[];
  edges: { id: string; source: string; target: string; label?: string }[];
};

/** 快照里的哈希 → 能取的地址。 */
export type ShareMedia = Record<string, { url: string; content_type: string; size?: number }>;

/** `GET /shares/{slug}`。 */
export type ShareDetail = {
  slug: string;
  title: string;
  version: number;
  visibility: Visibility;
  url?: string;
  owner: PublicUser;
  created_at?: string;
  updated_at: string;
  snapshot: BoardSnapshot;
  media: ShareMedia;
  /** 服务端第一次访问时从快照生成的 Open Graph 预览图(可以是相对路径)。 */
  og_image_url?: string | null;
};

/** `GET /users/{handle}`:作者主页一次取齐。 */
export type Profile = {
  user: PublicUser;
  workflows: WorkflowSummary[];
  workflows_count: number;
  plugins: PluginSummary[];
  plugins_count: number;
  boards: ShareSummary[];
  boards_count: number;
  /** 近一年逐日贡献(公开的版本 + 公开画板的分享),给热力图。 */
  contributions: DailyCount[];
};

/** `GET /stats/overview`。 */
export type StatsOverview = {
  users: number;
  workflows: number;
  plugins: number;
  shares: number;
  downloads: number;
  downloads_30d?: number;
  top_workflows?: WorkflowSummary[];
  top_plugins?: PluginSummary[];
};

/** 统计页画的四条线;`signups` 就是新注册用户。 */
export type Metric = "signups" | "submissions" | "downloads" | "shares";
export const METRICS: readonly Metric[] = ["signups", "submissions", "downloads", "shares"];

/** `GET /stats/timeseries?metric&days`。 */
export type Timeseries = { metric: Metric; days: number; points: { date: string; value: number }[] };

/** 服务端算好的、与上一个通过版本的差异(ADR §4「审核界面并排显示」)。 */
export type ReviewDiff = {
  previous_version: string | null;
  manifest: { added: Record<string, unknown>; removed: Record<string, unknown>; changed: Record<string, { from: unknown; to: unknown }> };
  permissions: { added: string[]; removed: string[] };
  tools: { added: string[]; removed: string[]; effects_changed: string[] };
  files: { added: string[]; removed: string[]; changed: string[] };
};

/** `GET /admin/queue` 的一项:一份待审的版本。 */
export type QueueItem = ItemVersion & {
  kind: ItemKind;
  item: { slug: string; title: string; plugin_id?: string | null; path: string };
  submitter: PublicUser;
  manifest: Record<string, unknown> | null;
  permissions: string[];
  tools: { name: string; description?: string }[];
  files: { path: string; size: number; sha256?: string }[];
  diff: ReviewDiff | null;
};

export type Report = {
  id: string;
  target: { kind: ItemKind | "share"; slug: string | null; title: string | null };
  reason: string;
  detail?: string | null;
  status: string;
  reporter?: PublicUser | null;
  created_at: string;
};

/** `GET /auth/config`:登录页要的公开配置。 */
export type AuthConfig = {
  terms_version: string;
  captcha: { provider: "tencent"; app_id: string } | null;
  sms_code_ttl_seconds?: number;
  sms_resend_seconds?: number;
};

/** 提交工作流 / 插件的回包:条目详情 + 这一版的审核状态。 */
export type SubmitResult = ItemSummary & { submission: ItemVersion };

/** 直传一个文件(头像):`POST /shares/uploads` 的回包。 */
export type UploadsResponse = {
  uploads: { sha256: string; method: string; url: string; headers?: Record<string, string>; expires_in?: number }[];
  skipped: string[];
};
