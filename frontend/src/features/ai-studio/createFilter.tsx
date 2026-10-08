/**
 * 创作页的种类(ADR 0055):筛选那一排、会话行上的小标、会话锁的「族」。
 *
 * 种类的键照后端(`generation_sessions.kind`):图像、视频、音乐与音效(`audio`,ADR 0022 定的键名,不改)、语音、播客。
 * 族:视觉(图像 + 视频 —— 保留「拿上一张图生视频」)、音乐、语音、播客。和后端 generation/sessions.SESSION_FAMILIES 同一张表。
 */
import { AudioLines, Film, Image as ImageIcon, Mic, Music, type LucideIcon } from "lucide-react";

import type { MessageKey } from "@/app/messages";
import { useI18n } from "@/app/preferences";
import { Chip } from "@/components/ui/chip";
import { CREATE_FILTERS, type CreateFilter } from "@/lib/aiStudioLink";

export const CREATION_KINDS = ["image", "video", "speech", "podcast", "audio"] as const;
export type CreationKind = (typeof CREATION_KINDS)[number];

const FAMILY: Record<CreationKind, string> = {
  image: "visual",
  video: "visual",
  audio: "music",
  speech: "speech",
  podcast: "podcast",
};

function isCreationKind(kind: string | null | undefined): kind is CreationKind {
  return Boolean(kind) && (CREATION_KINDS as readonly string[]).includes(kind!);
}

/** 和这一种同一族的那几种(有记录的会话,下拉只列这些)。认不出的种类不锁。 */
export function familyKinds(kind: string): CreationKind[] {
  if (!isCreationKind(kind)) return [...CREATION_KINDS];
  return CREATION_KINDS.filter((one) => FAMILY[one] === FAMILY[kind]);
}

/** 是生成管线的那几种(图像、视频、音乐)就是它,别的(语音、播客、全部、空)是 null。 */
export function generationKindOf(kind: string | null | undefined): "image" | "video" | "audio" | null {
  return kind === "image" || kind === "video" || kind === "audio" ? kind : null;
}

/** 每一种的小标:图标 + 一个词。筛选那一排和会话行用同一份。 */
export const KIND_BADGES: Record<CreationKind, { icon: LucideIcon; label: MessageKey }> = {
  image: { icon: ImageIcon, label: "createKindImage" },
  video: { icon: Film, label: "createKindVideo" },
  speech: { icon: Mic, label: "createKindSpeech" },
  podcast: { icon: AudioLines, label: "createKindPodcast" },
  audio: { icon: Music, label: "createKindAudio" },
};

const FILTER_LABELS: Record<CreateFilter, MessageKey> = {
  all: "createFilterAll",
  image: "createKindImage",
  video: "createKindVideo",
  speech: "createKindSpeech",
  podcast: "createKindPodcast",
  audio: "createKindAudio",
};

/** 这一种还没有会话时,列表里说什么(按种类说下一步做什么)。 */
export function emptySessionsKey(filter: CreateFilter): MessageKey {
  const keys: Record<CreateFilter, MessageKey> = {
    all: "createEmptyAll",
    image: "createEmptyImage",
    video: "createEmptyVideo",
    speech: "createEmptySpeech",
    podcast: "createEmptyPodcast",
    audio: "createEmptyAudio",
  };
  return keys[filter];
}

/** 会话行上的小标(图标 + 一个词)。种类认不出(老库里空的)就不摆。 */
export function KindBadge({ kind }: { kind: string | null | undefined }) {
  const t = useI18n();
  if (!isCreationKind(kind)) return null;
  const { icon: Icon, label } = KIND_BADGES[kind];
  return (
    <span className="inline-flex shrink-0 items-center gap-1 text-ui-2xs text-muted-foreground" data-kind-badge={kind}>
      <Icon size={11} aria-hidden />
      {t(label)}
    </span>
  );
}

/**
 * 会话列表上面那一排筛选:全部 · 图像 · 视频 · 语音 · 播客 · 音乐。左栏只有 240px 宽,一行摆不下六个:放不下就折行,
 * 不横着滚 —— 滚动条藏起来的话,后面那两种根本看不见(实测:「播客」「音乐」被裁在栏外)。
 */
export function CreateFilterRow({ value, onChange }: { value: CreateFilter; onChange: (next: CreateFilter) => void }) {
  const t = useI18n();
  return (
    <div
      role="tablist"
      aria-label={t("createFilterLabel")}
      className="flex shrink-0 flex-wrap gap-1 px-3 pt-3"
      data-create-filter=""
    >
      {CREATE_FILTERS.map((filter) => {
        const active = filter === value;
        const badge = filter === "all" ? null : KIND_BADGES[filter];
        const Icon = badge?.icon;
        return (
          <Chip key={filter} role="tab" selected={active} icon={Icon && <Icon aria-hidden />} onClick={() => onChange(filter)}>
            {t(FILTER_LABELS[filter])}
          </Chip>
        );
      })}
    </div>
  );
}
