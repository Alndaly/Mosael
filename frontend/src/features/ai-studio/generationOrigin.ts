/**
 * 一条创作会话是在哪一处开出来的(ADR 0052,后端 domain/generation/origins):创作页自己开的(`studio`)、「以前的语音 / 播客」
 * (`audio_page`)在列表上面;画板、工作流、资产、定时任务、智能体那段对话、ComfyUI 工作台开出来的收进「来自别处」。
 *
 * **名字是后端按看的人现查的**(`origin_name`):那一处删了是 `deleted`、他看不见是 `hidden`,名字和 id 都是空串 —— 于是只说
 * 「已删除的创意画板」「一段对话」,不把他看不见的标题写出来。别处开的会话标题空着,列表上就写那一处现在叫什么(画板改了名
 * 跟着变);迁移之前一次一条的老会话有自己的标题(提示词开头),那一处写在副标题上。
 */

import type { components } from "@/api/generated/schema";
import type { MessageKey } from "@/app/messages";
import type { useI18n } from "@/app/preferences";
import { STUDIO_PLACE } from "@/features/agent/places";
import { adoptAgentSession } from "@/features/agent/sessionSelection";
import { goToPlace } from "@/features/ai-studio/goToPlace";
import { workbenchAvailable } from "@/features/plugins/workbench/workbenchSession";
import { gotoAiChat } from "@/lib/aiStudioLink";
import { OPEN_SCHEDULED_TASK_EVENT, VIEW_RECORD_EVENTS, gotoRecord } from "@/lib/deepLink";

type Translate = ReturnType<typeof useI18n>;
type GenerationSession = components["schemas"]["GenerationSessionOut"];
export type OriginKind = GenerationSession["origin_kind"];
type Elsewhere = Exclude<OriginKind, "studio" | "audio_page">;

/** 在创作页这边开的:列在上面,不进「来自别处」。 */
const HERE: readonly OriginKind[] = ["studio", "audio_page"];

export function isFromElsewhere(session: Pick<GenerationSession, "origin_kind">): boolean {
  return !HERE.includes(session.origin_kind);
}

const NAMED: Record<Elsewhere, MessageKey> = {
  board: "createOriginBoard",
  workflow: "createOriginWorkflow",
  entity: "createOriginEntity",
  schedule: "createOriginSchedule",
  agent: "createOriginAgent",
  comfyui: "createOriginComfy",
};
const DELETED: Record<Elsewhere, MessageKey> = {
  board: "createOriginDeletedBoard",
  workflow: "createOriginDeletedWorkflow",
  entity: "createOriginDeletedEntity",
  schedule: "createOriginDeletedSchedule",
  agent: "createOriginDeletedAgent",
  comfyui: "createOriginDeletedComfy",
};
const HIDDEN: Record<Elsewhere, MessageKey> = {
  board: "createOriginHiddenBoard",
  workflow: "createOriginHiddenWorkflow",
  entity: "createOriginHiddenEntity",
  schedule: "createOriginHiddenSchedule",
  agent: "createOriginHiddenAgent",
  comfyui: "createOriginHiddenComfy",
};

/** 那一处叫什么:「创意画板《镜头与灵感》」「已删除的创意画板」「一段对话」「以前的语音」。创作页自己开的没有这一句。 */
export function originLabel(t: Translate, session: GenerationSession): string {
  const kind = session.origin_kind;
  if (kind === "studio") return "";
  if (kind === "audio_page") return t(session.origin_id === "podcast" ? "createOriginEarlierPodcast" : "createOriginEarlierSpeech");
  if (session.origin_state === "deleted") return t(DELETED[kind]);
  if (session.origin_state === "hidden") return t(HIDDEN[kind]);
  return t(NAMED[kind]).replace("{name}", session.origin_name);
}

/** 列表、标题栏上这条会话叫什么:有自己的标题就用它(创作页开的、用户改过名的、迁移之前的老会话);空着就是那一处的名字。 */
export function sessionTitle(t: Translate, session: GenerationSession): string {
  return session.title || originLabel(t, session) || t("generationNewSession");
}

/** 行上的副标题:有自己标题的别处会话,写那一处(标题空着的,标题本身就是那一处)。 */
export function originSubtitle(t: Translate, session: GenerationSession): string | undefined {
  return isFromElsewhere(session) && session.title ? originLabel(t, session) : undefined;
}

/** 「回到那里」去得了吗:那一处还在、看得见;ComfyUI 那张还得有工作台(桌面版)才开得了。 */
export function canGoToOrigin(session: GenerationSession): boolean {
  if (!isFromElsewhere(session) || session.origin_state !== "ok" || !session.origin_id) return false;
  return session.origin_kind !== "comfyui" || workbenchAvailable();
}

/** 去这条会话开出来的那一处:画板、工作流、ComfyUI 那张走对话的家那一套(goToPlace);资产、定时任务各自的页;对话去 AI Studio 的对话分区。 */
export function goToOrigin(workspaceId: string, session: GenerationSession): Promise<void> | void {
  const id = session.origin_id;
  switch (session.origin_kind) {
    case "board":
    case "workflow":
    case "comfyui":
      return goToPlace(workspaceId, { kind: session.origin_kind, id });
    case "entity":
      gotoRecord("/entities", VIEW_RECORD_EVENTS.entities, id);
      return;
    case "schedule":
      gotoRecord("/scheduler", OPEN_SCHEDULED_TASK_EVENT, id);
      return;
    case "agent":
      //: AI Studio 的对话分区列全部对话:选中那一段再切过去
      adoptAgentSession(workspaceId, STUDIO_PLACE, id);
      gotoAiChat();
      return;
  }
}
