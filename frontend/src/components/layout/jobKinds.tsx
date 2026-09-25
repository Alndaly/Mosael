/**
 * 任务种类在界面上的样子。**名字、要不要提示、改动了什么、在哪一页看,都由后端声明**
 * (`GET /api/jobs/kinds`,见 backend/app/domain/job_catalog.py 与 ADR-0018);这里只补两样后端
 * 不该知道的东西:每种任务的图标,和每种资源对应的缓存键。
 *
 * 此前这些是任务中心、子任务清单、任务详情里各自手写的表,彼此对不上。
 */

import React from "react";
import { useQuery } from "@tanstack/react-query";
import {
  Activity,
  AudioLines,
  AudioWaveform,
  Captions,
  Clapperboard,
  Download,
  Film,
  GitBranch,
  Link as LinkIcon,
  type LucideIcon,
  Mic,
  PenLine,
  Radio,
  Scissors,
  Send,
  Sparkles,
  Split,
} from "lucide-react";

import { fetchJobKinds, type Job, type JobKind } from "@/api/client";
import { STUDIO_VIEWS } from "@/components/layout/navLabels";
import { gotoRecord, VIEW_RECORD_EVENTS } from "@/lib/deepLink";

/** 每种任务的图标。后端目录里的每一种都要有(backend/tests/test_job_catalog.py 守着)。 */
export const JOB_KIND_ICONS: Record<string, LucideIcon> = {
  workflow: GitBranch,
  publish: Send,
  render: Download,
  transcribe: Mic,
  subtitle_dub: Captions,
  ai_generation: Sparkles,
  tts: AudioLines,
  podcast: Radio,
  url_import: LinkIcon,
  video_to_gif: Film,
  denoise_audio: AudioWaveform,
  separate_audio: Split,
  trim: Scissors,
  board_write: PenLine,
  proxy: Clapperboard,
};

/** 后端说"改动了哪种资源",这里说"那是哪些缓存"。 */
const RESOURCE_QUERY_KEYS: Record<string, readonly string[]> = {
  assets: ["assets", "asset", "waveform"],
  sequences: ["sequences"],
  transcripts: ["transcript"],
  workflows: ["workflows", "workflow-runs"],
  publish_tasks: ["publish-tasks"],
  generations: ["generation-jobs", "generation-sessions"],
  boards: ["boards"],
};

export type JobKindMeta = JobKind & { icon: LucideIcon };

const LOADING: JobKind = { kind: "", label: "", announce: "never", affects: [], view: null, record_field: null };

/** 按种类查它的界面信息。目录还没到时名字为空、不提示 —— 宁可晚一拍,不拿猜的说话。 */
export function useJobKinds() {
  const catalog = useQuery({ queryKey: ["job-kinds"], queryFn: fetchJobKinds, staleTime: Infinity });
  const lookup = React.useMemo(() => {
    const byKind = new Map((catalog.data?.kinds ?? []).map((entry) => [entry.kind, entry]));
    const fallback = catalog.data?.fallback ?? LOADING;
    return (kind: string): JobKindMeta => ({
      ...(byKind.get(kind) ?? { ...fallback, kind }),
      icon: JOB_KIND_ICONS[kind] ?? Activity,
    });
  }, [catalog.data]);
  return { kindOf: lookup, ready: catalog.isSuccess };
}

/** 这种任务做完后该作废的缓存键(第一段)。 */
export function queryKeysAffectedBy(meta: JobKind): string[] {
  return meta.affects.flatMap((resource) => RESOURCE_QUERY_KEYS[resource] ?? []);
}

/** 这种任务做完要不要说一声。 */
export function shouldAnnounce(meta: JobKind, status: string): boolean {
  if (meta.announce === "always") return true;
  return meta.announce === "failures" && status === "failed";
}

const KNOWN_VIEWS = new Set<string>(STUDIO_VIEWS);

/** 这条任务的结果在哪一页看;没有就返回 null。payload 里带着 project_id 时编辑器直接落到那个项目。 */
export function jobPage(job: Job, meta: JobKind): string | null {
  if (!meta.view || !KNOWN_VIEWS.has(meta.view)) return null;
  const projectId = ((job.payload ?? {}) as Record<string, unknown>).project_id;
  return `/${meta.view}${typeof projectId === "string" && projectId ? `?p=${projectId}` : ""}`;
}

/** 跳到这条任务的结果;目录声明了记录字段时直接打开那条记录。 */
export function gotoJobPage(job: Job, meta: JobKind): void {
  const page = jobPage(job, meta);
  if (!page) return;
  const payload = (job.payload ?? {}) as Record<string, unknown>;
  const recordId = meta.record_field ? payload[meta.record_field] : undefined;
  gotoRecord(page, meta.view ? VIEW_RECORD_EVENTS[meta.view] : undefined, recordId);
}

export function JobKindIcon({ meta, size = 13 }: { meta: JobKindMeta; size?: number }) {
  const Icon = meta.icon;
  return <Icon size={size} />;
}
