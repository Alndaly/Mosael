import React from "react";
import { useQuery } from "@tanstack/react-query";

import { getSkill, getSkillImport, type Confirmation } from "@/api/client";
import { errorText } from "@/api/errorMessage";
import { skillKeys } from "@/api/queryKeys";
import { useI18n } from "@/app/preferences";
import { Checkbox } from "@/components/ui/checkbox";
import { Truncate } from "@/components/ui/truncate";
import { useCardChoices } from "@/features/agent/cardChoices";
import { TextDiff } from "@/features/agent/NoteEditPreview";
import { formatBytes, SkillContent, type SkillContentFile } from "@/features/agent/skills/SkillContent";
import { diffText, type DiffSegment } from "@/lib/textDiff";

/**
 * 智能体改技能的确认卡上「要批的是什么」(ADR 0043)。通用参数表把一份技能画成几块 JSON,而这几张卡要人看的是:
 *
 * - 新建、复制成我的:**全文** —— 和设置页「看过全文再启用」同一个视图(SkillContent),外加「建好就启用」;
 * - 改:每个动了的文件「改之前 → 改之后」—— 和改笔记那张卡同一种对比(TextDiff);
 * - 开:全文(关只是一句话,标题已经说了);删:说明、文件数和大小;
 * - 从链接导入:和设置页导入同一个审阅 —— 每个文本文件的全文、二进制的大小、不认的字段、脚本标「不会执行」。
 *
 * 卡上的事实由后端开卡时算好、放在 payload 的 `_` 开头那几项里;复制和导入的其余文件不重复装进 payload,
 * 这里按需去读(原来那份技能 / 暂存着的那次导入)。「在用技能时提出的」那句由卡自己的后果提示摆(后端的 warning)。
 */
export const SKILL_CARD_PREVIEWS: Partial<Record<string, (payload: Record<string, unknown>, item: Confirmation) => React.ReactNode>> = {
  create_skill: (payload) => <NewSkillPreview payload={payload} />,
  copy_skill: (payload, item) => <CopiedSkillPreview payload={payload} workspaceId={item.workspace_id} />,
  update_skill: (payload) => <SkillChangesPreview payload={payload} />,
  set_skill_enabled: (payload, item) => <EnableSkillPreview payload={payload} workspaceId={item.workspace_id} />,
  delete_skill: (payload) => <DeleteSkillPreview payload={payload} />,
  import_skill: (payload, item) => <ImportSkillPreview payload={payload} workspaceId={item.workspace_id} />,
};

type FileRow = { path: string; size: number; script?: boolean; binary?: boolean };

function text(value: unknown): string {
  return typeof value === "string" ? value : "";
}

function rows(value: unknown): FileRow[] {
  return Array.isArray(value) ? (value as FileRow[]) : [];
}

function textFiles(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" ? (value as Record<string, unknown>) : {};
}

/** 卡上的开关(后端 ConfirmationOut.choices 里有 `enable` 才画)。拨的值由卡持有,批准时一起带走。 */
function EnableChoice({ label }: { label: "agentSkillCardEnable" | "agentSkillCardImportEnable" }) {
  const t = useI18n();
  const { values, set } = useCardChoices();
  if (!("enable" in values)) return null;
  return (
    <label className="flex w-fit cursor-pointer items-center gap-2 text-ui-sm" data-slot="skill-card-enable">
      <Checkbox checked={values.enable} onCheckedChange={(value) => set("enable", value === true)} />
      {t(label)}
    </label>
  );
}

function NewSkillPreview({ payload }: { payload: Record<string, unknown> }) {
  const written = textFiles(payload.files);
  const files: SkillContentFile[] = rows(payload._files).map((row) => ({
    ...row,
    text: row.path === "SKILL.md" ? text(payload._skill_md) : text(written[row.path]),
  }));
  return (
    <div className="grid min-w-0 gap-2.5" data-slot="skill-card-new">
      <SkillContent head={{ description: text(payload.description) }} files={files} />
      <EnableChoice label="agentSkillCardEnable" />
    </div>
  );
}

function CopiedSkillPreview({ payload, workspaceId }: { payload: Record<string, unknown>; workspaceId: string }) {
  const t = useI18n();
  const source = text(payload.name);
  //: 没改的文件照原样复制:全文从原来那份读(插件带的可能从没人看过,复制成我的再开,就得在这里看全)。
  const original = useQuery({ queryKey: skillKeys.detail(workspaceId, source), queryFn: () => getSkill(workspaceId, source) });
  const written = textFiles(payload.files);
  const originalText = new Map((original.data?.files ?? []).map((file) => [file.path, file.text ?? null]));
  const files: SkillContentFile[] = rows(payload._files).map((row) => ({
    ...row,
    text:
      row.path === "SKILL.md"
        ? text(payload._skill_md)
        : typeof written[row.path] === "string"
          ? text(written[row.path])
          : (originalText.get(row.path) ?? null),
  }));
  return (
    <div className="grid min-w-0 gap-2.5" data-slot="skill-card-copy">
      <p className="m-0 text-ui-xs text-muted-foreground">
        {t("agentSkillCardCopiedFrom").replace("{source}", text(payload._source_title) || source).replace("{label}", text(payload._source_label))}
      </p>
      <SkillContent head={{ description: text(payload._description) }} files={files} />
      <EnableChoice label="agentSkillCardEnable" />
    </div>
  );
}

type Change = { path: string; before: string; after: string | null; before_binary?: number };

/** 没改的地方在改动前后各留多少字:够认出改在哪一段,又不让一份长技能把真正的改动挤到「展开」后面。 */
export const CHANGE_CONTEXT_CHARS = 160;

/**
 * 只留改动和它前后的一截:开头那段原样的头(SKILL.md 的 `---` 头、前几步)、结尾那段、改动之间很长的没改的部分,
 * 各收成「…」加两头 CHANGE_CONTEXT_CHARS 字。不收的话改动常常落在第 400 个字之后 —— 卡上折起来时一处都看不到。
 */
export function aroundChanges(segments: DiffSegment[], context: number = CHANGE_CONTEXT_CHARS): DiffSegment[] {
  return segments.map((one, index) => {
    if (one.kind !== "same" || one.text.length <= context * 2) return one;
    const first = index === 0;
    const last = index === segments.length - 1;
    if (first && last) return one;
    if (first) return { ...one, text: `…${one.text.slice(-context)}` };
    if (last) return { ...one, text: `${one.text.slice(0, context)}…` };
    return { ...one, text: `${one.text.slice(0, context)}\n…\n${one.text.slice(-context)}` };
  });
}

function SkillChangesPreview({ payload }: { payload: Record<string, unknown> }) {
  const changes = Array.isArray(payload._changes) ? (payload._changes as Change[]) : [];
  return (
    <ol className="m-0 grid min-w-0 list-none gap-2 p-0" data-slot="skill-card-changes">
      {changes.map((change) => (
        <ChangedFile key={change.path} change={change} />
      ))}
    </ol>
  );
}

function ChangedFile({ change }: { change: Change }) {
  const t = useI18n();
  const [whole, setWhole] = React.useState(false);
  const added = change.before === "" && change.before_binary === undefined;
  const label = change.after === null ? t("agentSkillCardDeletedFile") : added ? t("agentSkillCardNewFile") : t("agentSkillCardChangedFile");
  const segments = diffText(change.before, change.after ?? "");
  const focused = aroundChanges(segments);
  const trimmed = focused.some((one, index) => one.text !== segments[index].text);
  return (
    <li className="grid min-w-0 gap-1" data-skill-change={change.path}>
      <span className="flex min-w-0 items-baseline gap-2 text-ui-xs">
        <Truncate className="min-w-0 font-mono text-foreground">{change.path}</Truncate>
        <span className="shrink-0 text-muted-foreground">{label}</span>
        {trimmed ? (
          <button
            type="button"
            aria-pressed={whole}
            className="ml-auto shrink-0 cursor-pointer border-0 bg-transparent p-0 text-ui-xs text-primary hover:underline"
            onClick={() => setWhole((value) => !value)}
          >
            {whole ? t("agentSkillCardChangesOnly") : t("agentSkillCardWholeFile")}
          </button>
        ) : null}
      </span>
      {change.before_binary !== undefined ? (
        <span className="text-ui-xs text-muted-foreground">
          {t("agentSkillCardBinaryBefore").replace("{size}", formatBytes(change.before_binary))}
        </span>
      ) : null}
      <TextDiff key={whole ? "whole" : "focused"} segments={whole ? segments : focused} />
    </li>
  );
}

function EnableSkillPreview({ payload, workspaceId }: { payload: Record<string, unknown>; workspaceId: string }) {
  const t = useI18n();
  const ref = text(payload.name);
  const enabling = payload.enabled === true;
  const detail = useQuery({ queryKey: skillKeys.detail(workspaceId, ref), queryFn: () => getSkill(workspaceId, ref), enabled: enabling });
  //: 关掉什么内容都不会再进系统提示:标题那一句就够了。
  if (!enabling) return null;
  if (detail.isError) return <p className="m-0 text-ui-xs text-destructive">{errorText(detail.error)}</p>;
  if (!detail.data) return <p className="m-0 text-ui-xs text-muted-foreground">{t("agentSkillCardLoading")}</p>;
  return (
    <div className="grid min-w-0 gap-2.5" data-slot="skill-card-enable-review">
      <p className="m-0 text-ui-xs text-muted-foreground">{t("agentSkillsReviewHint").replace("{source}", detail.data.source_label)}</p>
      <SkillContent head={detail.data} files={detail.data.files ?? []} />
    </div>
  );
}

function DeleteSkillPreview({ payload }: { payload: Record<string, unknown> }) {
  const t = useI18n();
  return (
    <div className="grid min-w-0 gap-1 text-ui-xs" data-slot="skill-card-delete">
      {text(payload._description) ? <p className="m-0 text-foreground">{text(payload._description)}</p> : null}
      <p className="m-0 text-muted-foreground">
        {t("agentSkillCardDeleteSize")
          .replace("{files}", String(Number(payload._files) || 0))
          .replace("{size}", formatBytes(Number(payload._bytes) || 0))}
      </p>
    </div>
  );
}

type StagedSkill = { name: string; title?: string; conflict?: string };

function ImportSkillPreview({ payload, workspaceId }: { payload: Record<string, unknown>; workspaceId: string }) {
  const t = useI18n();
  const importId = text(payload.import_id);
  const staged = useQuery({
    queryKey: skillKeys.staged(workspaceId, importId),
    queryFn: () => getSkillImport(workspaceId, importId),
    //: 暂存只写一次,不会变:读到了就不用再读。
    staleTime: Infinity,
    retry: false,
  });
  const picked = new Set((Array.isArray(payload._skills) ? (payload._skills as StagedSkill[]) : []).map((one) => one.name));
  if (staged.isError) return <p className="m-0 text-ui-xs text-destructive">{t("agentSkillCardImportGone")}</p>;
  if (!staged.data) return <p className="m-0 text-ui-xs text-muted-foreground">{t("agentSkillCardLoading")}</p>;
  return (
    <div className="grid min-w-0 gap-3" data-slot="skill-card-import">
      <p className="m-0 text-ui-xs text-muted-foreground">{t("agentSkillsImportHint")}</p>
      {staged.data.skills
        .filter((item) => picked.has(item.name))
        .map((item) => (
          <section key={item.name} className="grid min-w-0 gap-2 border-t border-divider pt-2.5 first:border-t-0 first:pt-0" data-import-skill={item.name}>
            <div className="flex min-w-0 flex-wrap items-baseline gap-x-2">
              <span className="text-ui-sm font-medium">{item.title || item.name}</span>
              {item.title ? <span className="font-mono text-ui-xs text-muted-foreground">{item.name}</span> : null}
            </div>
            {item.conflict === "workspace" ? <p className="m-0 text-ui-xs text-warning">{t("agentSkillCardReplaces")}</p> : null}
            <SkillContent head={item} files={item.files ?? []} />
          </section>
        ))}
      <EnableChoice label="agentSkillCardImportEnable" />
    </div>
  );
}
