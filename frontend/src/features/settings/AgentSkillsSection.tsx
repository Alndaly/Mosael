import React from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Copy, FileOutput, Eye, FolderInput, Pencil, Plus, Sparkles, Trash2, Import } from "lucide-react";
import { toast } from "sonner";

import {
  copySkill,
  deleteSkill,
  exportSkill,
  listSkills,
  setSkillEnabled,
  stageSkillArchive,
  stageSkillFolder,
  type AgentSkill,
  type AgentSkillImport,
  type Workspace,
} from "@/api/client";
import { errorText } from "@/api/errorMessage";
import { skillKeys } from "@/api/queryKeys";
import { useI18n } from "@/app/preferences";
import { ConfirmDialog, RenameDialog } from "@/components/app/modals";
import { SettingsEmpty, SettingsGroup, SettingsItemNote, SettingsItemRow, SettingsTag } from "@/components/settings/settings-layout";
import { Button } from "@/components/ui/button";
import { IconButton } from "@/components/ui/icon-button";
import { Switch } from "@/components/ui/switch";
import { Truncate } from "@/components/ui/truncate";
import { InlineMarkdown } from "@/components/markdown/InlineMarkdown";
import { SkillEditorDialog, type SkillEditorTarget } from "@/features/agent/skills/SkillEditorDialog";
import { SkillImportDialog } from "@/features/agent/skills/SkillImportDialog";
import { SkillReviewDialog } from "@/features/agent/skills/SkillReviewDialog";
import { saveBlobToDisk } from "@/lib/download";

/** 这些来源的技能**没人看过**:开之前先把全文摊开(ADR 0040 §6)。内置的、自己写的、导入时审阅过的不用。 */
export function needsReview(skill: AgentSkill): boolean {
  return skill.source === "plugin" || (skill.source === "workspace" && skill.origin === "folder");
}

/**
 * 设置 → 智能体 → 技能(ADR 0040 §7)。
 *
 * 三组:内置、这个工作区的、来自插件。每行一个开关;开着的才出现在智能体的系统提示里和输入框的「/」菜单里。
 * 新建、编辑、导入(先看全文再装)、导出成 `.zip`、把内置或插件的复制成自己的再改。
 *
 * 读的接口和系统提示用的是同一份清单(domain/agent/skills/catalog):这里开着的就是模型看得到的。
 */
export function AgentSkillsSection({ workspace }: { workspace: Workspace }) {
  const t = useI18n();
  const qc = useQueryClient();
  const skills = useQuery({ queryKey: skillKeys.all(workspace.id), queryFn: () => listSkills(workspace.id) });
  const refresh = () => qc.invalidateQueries({ queryKey: skillKeys.all(workspace.id) });
  const fail = (error: unknown) => toast.error(errorText(error));

  const [editor, setEditor] = React.useState<SkillEditorTarget | null>(null);
  const [reviewing, setReviewing] = React.useState<string | null>(null);
  const [deleting, setDeleting] = React.useState<AgentSkill | null>(null);
  const [copying, setCopying] = React.useState<AgentSkill | null>(null);
  const [staged, setStaged] = React.useState<AgentSkillImport | null>(null);
  const zipInput = React.useRef<HTMLInputElement>(null);
  const folderInput = React.useRef<HTMLInputElement>(null);

  const toggle = useMutation({
    mutationFn: ({ ref, enabled }: { ref: string; enabled: boolean }) => setSkillEnabled(workspace.id, ref, enabled),
    onSuccess: () => void refresh(),
    onError: fail,
  });
  const remove = useMutation({
    mutationFn: (ref: string) => deleteSkill(workspace.id, ref),
    onSuccess: () => {
      setDeleting(null);
      void refresh();
    },
    onError: fail,
  });
  const copy = useMutation({
    mutationFn: ({ ref, name }: { ref: string; name: string }) => copySkill(workspace.id, ref, name),
    onSuccess: (copied) => {
      setCopying(null);
      void refresh();
      setEditor({ kind: "edit", ref: copied.ref });
    },
    onError: fail,
  });
  const stage = useMutation({
    mutationFn: (input: { archive: File } | { folder: File[] }) =>
      "archive" in input ? stageSkillArchive(workspace.id, input.archive) : stageSkillFolder(workspace.id, input.folder),
    onSuccess: setStaged,
    onError: fail,
  });
  const download = async (skill: AgentSkill) => {
    try {
      saveBlobToDisk(await exportSkill(workspace.id, skill.ref), `${skill.ref.replace(":", "-")}.zip`);
    } catch (error) {
      fail(error);
    }
  };

  const rows = skills.data ?? [];
  const groups: { key: AgentSkill["source"]; title: string }[] = [
    { key: "builtin", title: t("agentSkillsGroupBuiltin") },
    { key: "workspace", title: t("agentSkillsGroupMine") },
    { key: "plugin", title: t("agentSkillsGroupPlugin") },
  ];

  return (
    <>
      <SettingsGroup
        title={t("agentSkillsTitle")}
        description={t("agentSkillsDesc")}
        actions={
          <div className="flex flex-wrap items-center gap-1.5">
            <Button variant="outline" size="sm" loading={stage.isPending} onClick={() => zipInput.current?.click()}>
              <Import size={13} /> {t("agentSkillsImportZip")}
            </Button>
            <Button variant="outline" size="sm" disabled={stage.isPending} onClick={() => folderInput.current?.click()}>
              <FolderInput size={13} /> {t("agentSkillsImportFolder")}
            </Button>
            <Button variant="outline" size="sm" onClick={() => setEditor({ kind: "create" })}>
              <Plus size={13} /> {t("agentSkillsNew")}
            </Button>
            <input
              ref={zipInput}
              type="file"
              accept=".zip,application/zip"
              hidden
              data-testid="skill-zip-input"
              onChange={(event) => {
                const file = event.target.files?.[0];
                event.target.value = "";
                if (file) stage.mutate({ archive: file });
              }}
            />
            <input
              ref={(node) => {
                folderInput.current = node;
                //: 选文件夹:React 不认识这个属性,直接写在 DOM 上(Electron 和浏览器都支持)。
                node?.setAttribute("webkitdirectory", "");
              }}
              type="file"
              multiple
              hidden
              data-testid="skill-folder-input"
              onChange={(event) => {
                const files = [...(event.target.files ?? [])];
                event.target.value = "";
                if (files.length) stage.mutate({ folder: files });
              }}
            />
          </div>
        }
      >
        {skills.isError ? (
          <SettingsEmpty
            icon={<Sparkles size={20} />}
            title={t("pageLoadError")}
            body={errorText(skills.error)}
            action={
              <Button variant="secondary" onClick={() => void skills.refetch()}>
                {t("retry")}
              </Button>
            }
          />
        ) : null}
      </SettingsGroup>
      {groups.map((group) => {
        const members = rows.filter((one) => one.source === group.key);
        if (group.key === "plugin" && members.length === 0) return null;
        return (
          <SettingsGroup key={group.key} title={group.title}>
            {members.length === 0 && skills.data ? (
              <SettingsEmpty
                icon={<Sparkles size={20} />}
                title={t("agentSkillsEmptyMine")}
                body={t("agentSkillsEmptyMineHint")}
                action={
                  <Button variant="outline" size="sm" onClick={() => setEditor({ kind: "create" })}>
                    <Plus size={13} /> {t("agentSkillsNew")}
                  </Button>
                }
              />
            ) : null}
            {members.map((skill) => (
              <SkillRow
                key={skill.ref}
                skill={skill}
                pending={toggle.isPending && toggle.variables?.ref === skill.ref}
                onToggle={(enabled) => {
                  if (enabled && needsReview(skill)) setReviewing(skill.ref);
                  else toggle.mutate({ ref: skill.ref, enabled });
                }}
                onOpen={() => setEditor(skill.editable ? { kind: "edit", ref: skill.ref } : { kind: "view", ref: skill.ref })}
                onExport={() => void download(skill)}
                onCopy={() => setCopying(skill)}
                onDelete={() => setDeleting(skill)}
              />
            ))}
          </SettingsGroup>
        );
      })}
      <SkillEditorDialog workspaceId={workspace.id} target={editor} onClose={() => setEditor(null)} />
      <SkillReviewDialog workspaceId={workspace.id} skillRef={reviewing} onClose={() => setReviewing(null)} />
      <SkillImportDialog workspaceId={workspace.id} staged={staged} onClose={() => setStaged(null)} />
      <ConfirmDialog
        open={deleting !== null}
        title={t("agentSkillsDeleteTitle").replace("{name}", deleting?.title ?? "")}
        body={t("agentSkillsDeleteBody")}
        confirmLabel={t("delete")}
        pending={remove.isPending}
        onCancel={() => setDeleting(null)}
        onConfirm={() => deleting && remove.mutate(deleting.ref)}
      />
      <RenameDialog
        open={copying !== null}
        title={t("agentSkillsCopyTitle")}
        initialValue={copying ? `my-${copying.name}`.slice(0, 64) : ""}
        pending={copy.isPending}
        confirmLabel={t("agentSkillsCopy")}
        onCancel={() => setCopying(null)}
        onSubmit={(name) => copying && copy.mutate({ ref: copying.ref, name })}
      />
    </>
  );
}

function SkillRow({
  skill,
  pending,
  onToggle,
  onOpen,
  onExport,
  onCopy,
  onDelete,
}: {
  skill: AgentSkill;
  pending: boolean;
  onToggle: (enabled: boolean) => void;
  onOpen: () => void;
  onExport: () => void;
  onCopy: () => void;
  onDelete: () => void;
}) {
  const t = useI18n();
  return (
    <SettingsItemRow
      className="group/skill"
      label={<span data-skill-row={skill.ref}>{skill.title}</span>}
      meta={[skill.title !== skill.ref ? <span key="ref" className="font-mono">{skill.ref}</span> : null, skill.source_label]}
      tags={needsReview(skill) && !skill.enabled ? <SettingsTag tone="warning">{t("agentSkillsUnreviewed")}</SettingsTag> : undefined}
      description={
        <Truncate lines={2}>
          <InlineMarkdown text={skill.description} links={false} />
        </Truncate>
      }
      notes={skill.problem ? <SettingsItemNote tone="destructive">{t("agentSkillsProblem").replace("{problem}", skill.problem)}</SettingsItemNote> : undefined}
    >
      <div className="flex items-center gap-0.5">
        <IconButton label={skill.editable ? t("agentSkillsEdit") : t("agentSkillsView")} onClick={onOpen}>
          {skill.editable ? <Pencil size={13} /> : <Eye size={13} />}
        </IconButton>
        <IconButton label={t("agentSkillsExport")} onClick={onExport}>
          <FileOutput size={13} />
        </IconButton>
        {!skill.editable && (
          <IconButton label={t("agentSkillsCopy")} onClick={onCopy}>
            <Copy size={13} />
          </IconButton>
        )}
        {skill.editable && (
          <IconButton className="hover:text-destructive" label={t("delete")} onClick={onDelete}>
            <Trash2 size={13} />
          </IconButton>
        )}
      </div>
      <Switch
        checked={skill.enabled}
        disabled={pending || (!skill.enabled && Boolean(skill.problem))}
        aria-label={t("agentSkillsEnable").replace("{name}", skill.title)}
        onCheckedChange={onToggle}
      />
    </SettingsItemRow>
  );
}
