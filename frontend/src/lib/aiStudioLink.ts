import { OPEN_CREATION_SESSION_EVENT, emitOpenEvent, gotoRecord } from "@/lib/deepLink";

export { OPEN_CREATION_SESSION_EVENT };

/**
 * AI Studio 的两个分区和它的深链(ADR 0055 §9)。
 *
 * `#/ai?tab=chat|create[&session=<创作会话 id>][&kind=<筛选>]`。AiStudio 读完就把地址还原成 `#/ai`:分区当场切,会话 id 和
 * 筛选经信箱交给创作页(它可能还没挂上、列表还没到)—— 和画板的 `?board=` 同一条路。不带 `tab` 的老地址(书签、只改 hash 的
 * 老调用)落在上次停的那个分区。
 *
 * 要去对话分区的地方一律写 `tab=chat`:此前它们只跳 `#/ai`,上次停在「生成 / 音频」的话,「回到那段对话」落错地方。
 */
export const STUDIO_TABS = ["chat", "create"] as const;
export type StudioTab = (typeof STUDIO_TABS)[number];

/** 创作页的筛选:全部,或者某一种(`audio` 是音乐与音效 —— 键名照生成管线的种类,ADR 0022)。 */
export const CREATE_FILTERS = ["all", "image", "video", "speech", "podcast", "audio"] as const;
export type CreateFilter = (typeof CREATE_FILTERS)[number];

/** 「筛选换成这一种」:模型库「用它生成」带着种类过来。 */
export const CREATION_FILTER_EVENT = "mosael:creation-filter";

export function isCreateFilter(value: unknown): value is CreateFilter {
  return typeof value === "string" && (CREATE_FILTERS as readonly string[]).includes(value);
}

export function aiStudioHref(tab: StudioTab, { session, kind }: { session?: string; kind?: CreateFilter } = {}): string {
  const query = new URLSearchParams({ tab });
  if (session) query.set("session", session);
  if (kind) query.set("kind", kind);
  return `#/ai?${query.toString()}`;
}

/** 地址里的 AI Studio 深链;不是 `#/ai` 那一页就是 null。 */
export function parseAiStudioHash(hash: string): { tab: StudioTab | null; session: string; kind: CreateFilter | null } | null {
  const [path, query = ""] = hash.replace(/^#\/?/, "").split("?");
  if (path !== "ai") return null;
  const params = new URLSearchParams(query);
  const tab = params.get("tab");
  const kind = params.get("kind");
  return {
    tab: (STUDIO_TABS as readonly string[]).includes(tab ?? "") ? (tab as StudioTab) : null,
    session: params.get("session") ?? "",
    kind: isCreateFilter(kind) ? kind : null,
  };
}

/** 去对话分区(智能体那段对话、技能起草、交给智能体)。 */
export function gotoAiChat(): void {
  window.location.hash = aiStudioHref("chat");
}

/** 打开某一条创作会话。 */
export function openCreationSession(sessionId: string): void {
  gotoRecord(aiStudioHref("create"), OPEN_CREATION_SESSION_EVENT, sessionId);
}

/** 去创作分区,筛选换成这一种(模型库「用它生成」)。 */
export function gotoCreate(kind?: CreateFilter): void {
  window.location.hash = aiStudioHref("create");
  if (kind) emitOpenEvent(CREATION_FILTER_EVENT, kind);
}

/** 分区记在本机的那个键(usePersistentTab 的 key)。 */
export const STUDIO_TAB_KEY = "ai-studio";
/** 创作页的筛选记在本机的那个键。 */
export const CREATE_FILTER_KEY = "ai-studio-create-filter";

/** 创作页「上次开着哪条会话」(每个工作区一个)。 */
export function creationSessionKey(workspaceId: string): string {
  return `${GENERATION_SESSION_PREFIX}${workspaceId}.create`;
}

const GENERATION_SESSION_PREFIX = "mosael.generation.session.";

/**
 * 本机存的老形状 → 「对话 | 创作」(lib/localMigrations 的一步,ADR 0055 §9)。幂等,迁完删旧键:
 *
 * - 分区 `generate` / `audio` → `create`(`chat` 不动);
 * - 上次停在「音频」的,那一格(语音 / 播客 / 音乐)变成筛选;停在「生成」的筛选是全部;然后删掉音频那一格的键;
 * - 「上次开着哪条会话」两页各一个键(`.visual` / `.audio`)合成一个 `.create`:上次停在音乐那一格的取音频那页的,
 *   否则先取生成页的、没有才取音频页的。
 */
export function migrateAiStudioCreate(storage: Storage): void {
  const tabKey = `mosael:tab:${STUDIO_TAB_KEY}`;
  const audioKey = "mosael:tab:ai-studio-audio";
  const filterKey = `mosael:tab:${CREATE_FILTER_KEY}`;
  const tab = storage.getItem(tabKey);
  const audioMode = storage.getItem(audioKey);
  const FILTER_OF_AUDIO_MODE: Record<string, CreateFilter> = { speech: "speech", podcast: "podcast", music: "audio" };
  if (tab === "generate" || tab === "audio") {
    storage.setItem(tabKey, "create");
    if (storage.getItem(filterKey) === null) {
      storage.setItem(filterKey, tab === "audio" ? FILTER_OF_AUDIO_MODE[audioMode ?? ""] ?? "all" : "all");
    }
  }
  if (audioMode !== null) storage.removeItem(audioKey);

  const keys: string[] = [];
  for (let index = 0; index < storage.length; index += 1) {
    const key = storage.key(index);
    if (key?.startsWith(GENERATION_SESSION_PREFIX) && /\.(visual|audio)$/.test(key)) keys.push(key);
  }
  const workspaces = new Set(keys.map((key) => key.slice(GENERATION_SESSION_PREFIX.length).replace(/\.(visual|audio)$/, "")));
  const musicFirst = tab === "audio" && audioMode === "music";
  for (const workspace of workspaces) {
    const visual = `${GENERATION_SESSION_PREFIX}${workspace}.visual`;
    const audio = `${GENERATION_SESSION_PREFIX}${workspace}.audio`;
    const merged = creationSessionKey(workspace);
    if (storage.getItem(merged) === null) {
      const [first, second] = musicFirst ? [audio, visual] : [visual, audio];
      const value = storage.getItem(first) ?? storage.getItem(second);
      if (value) storage.setItem(merged, value);
    }
    storage.removeItem(visual);
    storage.removeItem(audio);
  }
}
