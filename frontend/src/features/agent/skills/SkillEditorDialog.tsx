import React from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Plus, Trash2 } from "lucide-react";
import { toast } from "sonner";

import {
  createSkill,
  deleteSkillFile,
  getSkill,
  putSkillFile,
  updateSkill,
  type AgentSkillDetail,
  type AgentSkillDraft,
  type AgentSkillWrite,
} from "@/api/client";
import { errorText } from "@/api/errorMessage";
import { skillKeys } from "@/api/queryKeys";
import { useI18n } from "@/app/preferences";
import { DIALOG_FIELD, ModalShell } from "@/components/app/modals";
import { Button } from "@/components/ui/button";
import { IconButton } from "@/components/ui/icon-button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Truncate } from "@/components/ui/truncate";
import { SkillContent, formatBytes } from "@/features/agent/skills/SkillContent";

/** 技能名:小写英文字母、数字和单个连字符(和格式包 `NAME_RE` 同一条)。 */
export const SKILL_NAME_RE = /^[a-z0-9]+(?:-[a-z0-9]+)*$/;
export const MAX_SKILL_NAME = 64;
export const MAX_SKILL_DESCRIPTION = 1024;

/** 打开编辑器的三种方式:新建(可带一份「存成技能」起草的稿)、改一个工作区技能、看一个只读的(内置 / 插件)。 */
export type SkillEditorTarget =
  | { kind: "create"; draft?: AgentSkillDraft; fromConversation?: boolean }
  | { kind: "edit"; ref: string }
  | { kind: "view"; ref: string };

type Fields = { name: string; title: string; description: string; license: string; compatibility: string; body: string };

const EMPTY: Fields = { name: "", title: "", description: "", license: "", compatibility: "", body: "" };

function fieldsOf(skill: AgentSkillDetail): Fields {
  return {
    name: skill.name,
    title: skill.title === skill.name ? "" : skill.title,
    description: skill.description,
    license: skill.license ?? "",
    compatibility: skill.compatibility ?? "",
    body: skill.body ?? "",
  };
}

/** 显示名是英文时顺手给一个技能名;中文就留空让人自己起(不猜拼音)。 */
export function suggestName(title: string): string {
  const slug = title
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .replace(/-{2,}/g, "-")
    .slice(0, MAX_SKILL_NAME)
    .replace(/-+$/g, "");
  return SKILL_NAME_RE.test(slug) ? slug : "";
}

/**
 * 新建 / 编辑 / 查看一个技能(ADR 0040 §7):头上的字段(名字、显示名、说明、许可证、环境要求)、Markdown 的正文、
 * 和它带的文件。新建保存之后就地变成编辑,好接着添加文件(文件挂在已有的技能上)。
 *
 * 「存成技能」也走这里:起草的稿填进来,人改完才保存。
 */
export function SkillEditorDialog({
  workspaceId,
  target,
  onClose,
}: {
  workspaceId: string;
  /** null = 关着。 */
  target: SkillEditorTarget | null;
  onClose: () => void;
}) {
  const t = useI18n();
  const qc = useQueryClient();
  const formId = React.useId();
  //: 新建保存之后改成编辑那一个(不关弹窗):文件要挂在已有的技能上。
  const [savedRef, setSavedRef] = React.useState<string | null>(null);
  const ref = target && target.kind !== "create" ? target.ref : savedRef;
  const readOnly = target?.kind === "view";
  const detail = useQuery({
    queryKey: skillKeys.detail(workspaceId, ref ?? ""),
    queryFn: () => getSkill(workspaceId, ref ?? ""),
    enabled: Boolean(target && ref),
  });
  const [fields, setFields] = React.useState<Fields>(EMPTY);
  const [nameTouched, setNameTouched] = React.useState(false);

  //: 打开时按来源填:新建填起草稿(或空),编辑等详情回来再填。**只在打开的那一下填** —— 调用方每次渲染
  //: 都可能给一个新的 target 对象,跟着它的身份走的话,打着字表单就被重置了。
  const openKey = target ? `${target.kind}:${target.kind === "create" ? "" : target.ref}` : "";
  const targetRef = React.useRef(target);
  targetRef.current = target;
  React.useEffect(() => {
    const opened = targetRef.current;
    if (!opened) return;
    setSavedRef(null);
    setNameTouched(false);
    if (opened.kind === "create") {
      const draft = opened.draft;
      setFields(draft ? { ...EMPTY, name: draft.name, title: draft.title, description: draft.description, body: draft.body } : EMPTY);
    }
  }, [openKey]);
  const loadedFor = React.useRef<string | null>(null);
  React.useEffect(() => {
    if (!detail.data || !target || target.kind === "create") return;
    if (loadedFor.current === `${openKey}:${detail.data.ref}`) return;
    loadedFor.current = `${openKey}:${detail.data.ref}`;
    setFields(fieldsOf(detail.data));
  }, [detail.data, openKey, target]);
  React.useEffect(() => {
    if (!target) loadedFor.current = null;
  }, [target]);

  const refresh = () => qc.invalidateQueries({ queryKey: skillKeys.all(workspaceId) });
  const body = (): AgentSkillWrite => ({
    name: fields.name.trim(),
    title: fields.title.trim(),
    description: fields.description.trim(),
    license: fields.license.trim(),
    compatibility: fields.compatibility.trim(),
    body: fields.body,
    from_conversation: target?.kind === "create" && Boolean(target.fromConversation),
  });
  const save = useMutation({
    mutationFn: () => (ref ? updateSkill(workspaceId, ref, body()) : createSkill(workspaceId, body())),
    onSuccess: (saved) => {
      void refresh();
      qc.setQueryData(skillKeys.detail(workspaceId, saved.ref), saved);
      toast.success(t("agentSkillsSaved"));
      if (!ref) {
        //: 新建之后留在这个弹窗里,变成编辑那一个 —— 接着可以加文件。
        setSavedRef(saved.ref);
        loadedFor.current = `${openKey}:${saved.ref}`;
        return;
      }
      if (saved.ref !== ref) {
        //: 改了名字:之后的操作对着新名字。
        setSavedRef(saved.ref);
      }
      onClose();
    },
    onError: (error) => toast.error(errorText(error)),
  });

  const nameValid = SKILL_NAME_RE.test(fields.name.trim()) && fields.name.trim().length <= MAX_SKILL_NAME;
  const canSave = !readOnly && nameValid && fields.description.trim().length > 0 && !save.isPending;
  const title = readOnly
    ? t("agentSkillsEditorView")
    : ref
      ? t("agentSkillsEditorEdit")
      : t("agentSkillsEditorNew");
  const set = (key: keyof Fields) => (event: React.ChangeEvent<HTMLInputElement | HTMLTextAreaElement>) => {
    const value = event.target.value;
    setFields((current) => {
      const next = { ...current, [key]: value };
      //: 名字没人动过时跟着英文显示名走。
      if (key === "title" && !nameTouched && !ref) next.name = suggestName(value) || current.name;
      return next;
    });
    if (key === "name") setNameTouched(true);
  };

  return (
    <ModalShell
      open={target !== null}
      onOpenChange={(next) => !next && !save.isPending && onClose()}
      title={title}
      className="w-[720px] max-w-[calc(100vw-32px)]"
      footer={
        readOnly ? (
          <Button type="button" variant="outline" onClick={onClose}>
            {t("close")}
          </Button>
        ) : (
          <>
            <Button type="button" variant="outline" disabled={save.isPending} onClick={onClose}>
              {t("cancel")}
            </Button>
            <Button type="submit" form={formId} disabled={!canSave} loading={save.isPending}>
              {t("save")}
            </Button>
          </>
        )
      }
    >
      {readOnly ? (
        detail.data ? (
          <SkillContent head={detail.data} files={detail.data.files ?? []} />
        ) : null
      ) : (
        <form
          id={formId}
          className="grid gap-4"
          onSubmit={(event) => {
            event.preventDefault();
            if (canSave) save.mutate();
          }}
        >
          {target?.kind === "create" && target.draft ? (
            <p className="m-0 text-ui-xs text-muted-foreground" data-slot="skill-draft-hint">
              {t("agentSkillDraftHint")}
            </p>
          ) : null}
          <div className="grid gap-3 sm:grid-cols-2">
            <label className={DIALOG_FIELD}>
              <span>{t("agentSkillsFieldTitle")}</span>
              <Input value={fields.title} maxLength={80} onChange={set("title")} placeholder={t("agentSkillsFieldTitlePlaceholder")} />
              <small>{t("agentSkillsFieldTitleHint")}</small>
            </label>
            <label className={DIALOG_FIELD}>
              <span>{t("agentSkillsFieldName")}</span>
              <Input
                value={fields.name}
                maxLength={MAX_SKILL_NAME}
                onChange={set("name")}
                placeholder="short-video-ads"
                aria-invalid={fields.name !== "" && !nameValid}
                className="font-mono"
              />
              <small className={fields.name !== "" && !nameValid ? "!text-destructive" : undefined}>
                {fields.name !== "" && !nameValid ? t("agentSkillsFieldNameInvalid") : t("agentSkillsFieldNameHint")}
              </small>
            </label>
          </div>
          <label className={DIALOG_FIELD}>
            <span>{t("agentSkillsFieldDescription")}</span>
            <Textarea rows={2} value={fields.description} maxLength={MAX_SKILL_DESCRIPTION} onChange={set("description")}
              placeholder={t("agentSkillsFieldDescriptionPlaceholder")} />
            <small className="flex justify-between gap-3">
              <span>{t("agentSkillsFieldDescriptionHint")}</span>
              <span className="shrink-0 tabular-nums">
                {fields.description.length} / {MAX_SKILL_DESCRIPTION}
              </span>
            </small>
          </label>
          <label className={DIALOG_FIELD}>
            <span>{t("agentSkillsFieldBody")}</span>
            <Textarea rows={12} value={fields.body} onChange={set("body")} className="font-mono text-ui-xs"
              placeholder={t("agentSkillsFieldBodyPlaceholder")} />
            <small>{t("agentSkillsFieldBodyHint")}</small>
          </label>
          <div className="grid gap-3 sm:grid-cols-2">
            <label className={DIALOG_FIELD}>
              <span>{t("agentSkillsFieldLicense")}</span>
              <Input value={fields.license} maxLength={500} onChange={set("license")} placeholder="MIT" />
            </label>
            <label className={DIALOG_FIELD}>
              <span>{t("agentSkillsFieldCompatibility")}</span>
              <Input value={fields.compatibility} maxLength={500} onChange={set("compatibility")} />
            </label>
          </div>
          <SkillFiles workspaceId={workspaceId} skill={ref ? detail.data ?? null : null} />
        </form>
      )}
    </ModalShell>
  );
}

/** 技能带的文件:列出来,能加、能换、能删。SKILL.md 本身在上面的表单里改,这里不列。 */
function SkillFiles({ workspaceId, skill }: { workspaceId: string; skill: AgentSkillDetail | null }) {
  const t = useI18n();
  const qc = useQueryClient();
  const input = React.useRef<HTMLInputElement>(null);
  const [folder, setFolder] = React.useState("references");
  const apply = (next: AgentSkillDetail) => {
    qc.setQueryData(skillKeys.detail(workspaceId, next.ref), next);
    void qc.invalidateQueries({ queryKey: skillKeys.all(workspaceId) });
  };
  const upload = useMutation({
    mutationFn: async (files: File[]) => {
      let last: AgentSkillDetail | null = null;
      for (const file of files) {
        const prefix = folder.trim().replace(/^\/+|\/+$/g, "");
        last = await putSkillFile(workspaceId, skill!.ref, prefix ? `${prefix}/${file.name}` : file.name, file);
      }
      return last;
    },
    onSuccess: (next) => next && apply(next),
    onError: (error) => toast.error(errorText(error)),
  });
  const remove = useMutation({
    mutationFn: (path: string) => deleteSkillFile(workspaceId, skill!.ref, path),
    onSuccess: apply,
    onError: (error) => toast.error(errorText(error)),
  });
  const files = (skill?.files ?? []).filter((file) => file.path !== "SKILL.md");
  return (
    <div className="grid gap-2" data-slot="skill-files">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className="text-ui-sm font-medium">{t("agentSkillsFiles")}</span>
        {skill ? (
          <div className="flex items-center gap-1.5">
            <Input
              aria-label={t("agentSkillsFileFolder")}
              value={folder}
              onChange={(event) => setFolder(event.target.value)}
              size="sm"
              className="w-[140px] font-mono text-ui-xs"
            />
            <Button type="button" variant="outline" size="sm" loading={upload.isPending} onClick={() => input.current?.click()}>
              <Plus size={12} /> {t("agentSkillsAddFile")}
            </Button>
            <input
              ref={input}
              type="file"
              multiple
              hidden
              data-testid="skill-file-input"
              onChange={(event) => {
                const picked = [...(event.target.files ?? [])];
                event.target.value = "";
                if (picked.length) upload.mutate(picked);
              }}
            />
          </div>
        ) : null}
      </div>
      <small className="text-ui-xs text-muted-foreground">{skill ? t("agentSkillsFilesHint") : t("agentSkillsFilesAfterSave")}</small>
      {files.map((file) => (
        <div key={file.path} className="flex min-w-0 items-center gap-2 text-ui-xs" data-skill-file={file.path}>
          <Truncate className="min-w-0 flex-1 font-mono">{file.path}</Truncate>
          {file.script && <span className="shrink-0 text-warning">{t("agentSkillsScriptBadge")}</span>}
          <span className="shrink-0 tabular-nums text-muted-foreground">{formatBytes(file.size)}</span>
          <IconButton className="hover:text-destructive" label={t("delete")} onClick={() => remove.mutate(file.path)}>
            <Trash2 size={12} />
          </IconButton>
        </div>
      ))}
    </div>
  );
}
