import React from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";

import { commitSkillImport, type AgentSkillImport, type AgentSkillImportChoice, type AgentSkillImportItem } from "@/api/client";
import { errorText } from "@/api/errorMessage";
import { skillKeys } from "@/api/queryKeys";
import { useI18n } from "@/app/preferences";
import { DIALOG_FIELD, ModalShell } from "@/components/app/modals";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { SkillContent } from "@/features/agent/skills/SkillContent";
import { MAX_SKILL_NAME, SKILL_NAME_RE } from "@/features/agent/skills/SkillEditorDialog";

type Choice = { include: boolean; renameTo: string; replace: boolean; enable: boolean };

function initialChoice(item: AgentSkillImportItem): Choice {
  //: 和内置技能撞名的必须换名字:先给一个建议,人可以改。
  return { include: true, renameTo: item.conflict === "builtin" ? `${item.name}-imported`.slice(0, MAX_SKILL_NAME) : "", replace: false, enable: false };
}

/** 这一条的选择能不能落地 —— 撞名了就得换名字或替换(内置的只能换名字)。返回问题,没问题是空串。 */
function problemOf(item: AgentSkillImportItem, choice: Choice, t: (key: "agentSkillsFieldNameInvalid" | "agentSkillsImportConflictBuiltin" | "agentSkillsImportConflictMine") => string): string {
  if (!choice.include) return "";
  const renamed = choice.renameTo.trim();
  if (renamed && !SKILL_NAME_RE.test(renamed)) return t("agentSkillsFieldNameInvalid");
  if (item.conflict === "builtin" && (!renamed || renamed === item.name)) return t("agentSkillsImportConflictBuiltin");
  if (item.conflict === "workspace" && !choice.replace && (!renamed || renamed === item.name)) return t("agentSkillsImportConflictMine");
  return "";
}

/**
 * 导入技能的审阅(ADR 0040 §6):**看过全文再装**。
 *
 * 压缩包 / 文件夹已经在后端读好、放进了暂存,这里把每个技能的每个文件摊开给人看;要装哪几个、换不换名字、撞名时
 * 替不替换、装好开不开,都在这一屏定。「装好就启用」默认不勾 —— 导入的是别人写的做法,开它是一个信任决定。
 */
export function SkillImportDialog({
  workspaceId,
  staged,
  onClose,
}: {
  workspaceId: string;
  staged: AgentSkillImport | null;
  onClose: () => void;
}) {
  const t = useI18n();
  const qc = useQueryClient();
  const [choices, setChoices] = React.useState<Record<string, Choice>>({});
  React.useEffect(() => {
    if (!staged) return;
    setChoices(Object.fromEntries(staged.skills.map((item) => [item.name, initialChoice(item)])));
  }, [staged]);
  const commit = useMutation({
    mutationFn: () => {
      const picked: AgentSkillImportChoice[] = (staged?.skills ?? [])
        .filter((item) => choices[item.name]?.include)
        .map((item) => {
          const choice = choices[item.name];
          return { name: item.name, rename_to: choice.renameTo.trim(), replace: choice.replace, enable: choice.enable };
        });
      return commitSkillImport(workspaceId, staged!.import_id, picked);
    },
    onSuccess: (installed) => {
      void qc.invalidateQueries({ queryKey: skillKeys.all(workspaceId) });
      toast.success(t("agentSkillsImported").replace("{n}", String(installed.length)));
      onClose();
    },
    onError: (error) => toast.error(errorText(error)),
  });
  const items = staged?.skills ?? [];
  const problems = items.map((item) => (choices[item.name] ? problemOf(item, choices[item.name], t) : ""));
  const included = items.filter((item) => choices[item.name]?.include).length;
  const canCommit = included > 0 && problems.every((problem) => !problem) && !commit.isPending;
  const update = (name: string, patch: Partial<Choice>) =>
    setChoices((current) => ({ ...current, [name]: { ...current[name], ...patch } }));

  return (
    <ModalShell
      open={staged !== null}
      onOpenChange={(next) => !next && !commit.isPending && onClose()}
      title={t("agentSkillsImportTitle")}
      className="w-[760px] max-w-[calc(100vw-32px)]"
      footer={
        <>
          <Button variant="outline" disabled={commit.isPending} onClick={onClose}>
            {t("cancel")}
          </Button>
          <Button disabled={!canCommit} loading={commit.isPending} onClick={() => commit.mutate()}>
            {t("agentSkillsImportConfirm")}
          </Button>
        </>
      }
    >
      <div className="grid gap-5">
        <p className="m-0 text-ui-sm text-muted-foreground">{t("agentSkillsImportHint")}</p>
        {items.map((item, index) => {
          const choice = choices[item.name] ?? initialChoice(item);
          return (
            <section key={item.name} className="grid gap-3 border-t border-divider pt-4 first:border-t-0 first:pt-0" data-import-skill={item.name}>
              <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
                <label className="flex cursor-pointer items-center gap-2 text-ui-md font-medium">
                  <Checkbox
                    checked={choice.include}
                    onCheckedChange={(value) => update(item.name, { include: value === true })}
                    aria-label={t("agentSkillsImportInclude")}
                  />
                  {item.title || item.name}
                </label>
                {item.title ? <span className="font-mono text-ui-xs text-muted-foreground">{item.name}</span> : null}
              </div>
              {item.folder && item.folder !== item.name ? (
                <p className="m-0 text-ui-xs text-muted-foreground">
                  {t("agentSkillsImportFolderNote").replace("{folder}", item.folder).replace("{name}", item.name)}
                </p>
              ) : null}
              {choice.include && (
                <div className="grid gap-3 sm:grid-cols-2">
                  <label className={DIALOG_FIELD}>
                    <span>{t("agentSkillsImportRename")}</span>
                    <Input
                      value={choice.renameTo}
                      placeholder={item.name}
                      maxLength={MAX_SKILL_NAME}
                      className="font-mono"
                      onChange={(event) => update(item.name, { renameTo: event.target.value })}
                    />
                    {problems[index] ? <small className="!text-destructive">{problems[index]}</small> : null}
                  </label>
                  <div className="grid content-start gap-2 pt-6 text-ui-sm">
                    {item.conflict === "workspace" && (
                      <label className="flex cursor-pointer items-center gap-2">
                        <Checkbox checked={choice.replace} onCheckedChange={(value) => update(item.name, { replace: value === true })} />
                        {t("agentSkillsImportReplace")}
                      </label>
                    )}
                    <label className="flex cursor-pointer items-center gap-2" data-slot="import-enable">
                      <Checkbox checked={choice.enable} onCheckedChange={(value) => update(item.name, { enable: value === true })} />
                      {t("agentSkillsImportEnable")}
                    </label>
                  </div>
                </div>
              )}
              <SkillContent head={item} files={item.files ?? []} />
            </section>
          );
        })}
      </div>
    </ModalShell>
  );
}
