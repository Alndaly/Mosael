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
 *
 * 中间那块表单**一行一件事、每行占满内容宽**:改名字段自己一行,两个勾选各自一行、整行可点。此前改名和勾选并排
 * 成两列,输入框只占半行,勾选那列还得靠 `pt-6` 硬凑到和左列标签齐平。
 */
export function SkillImportDialog({
  workspaceId,
  staged,
  onClose,
  onInstalled,
}: {
  workspaceId: string;
  staged: AgentSkillImport | null;
  onClose: () => void;
  /** 装好了(在 onClose 之前)。对话里「发现 N 个技能」的卡靠它收起 —— 只是关掉审阅的话卡要留着。 */
  onInstalled?: () => void;
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
      onInstalled?.();
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
          //: 显示名和装进去的名字是同一个时只写一遍 —— 同一个名字写两遍,人还得猜为什么。
          const namedDifferently = Boolean(item.title) && item.title !== item.name;
          return (
            <section key={item.name} className="grid gap-3 border-t border-divider pt-4 first:border-t-0 first:pt-0" data-import-skill={item.name}>
              <div className="flex min-w-0 flex-wrap items-center gap-x-3 gap-y-1">
                <label className="flex cursor-pointer items-center gap-2 text-ui-md font-medium">
                  <Checkbox
                    checked={choice.include}
                    onCheckedChange={(value) => update(item.name, { include: value === true })}
                    aria-label={t("agentSkillsImportInclude")}
                  />
                  {item.title || item.name}
                </label>
                {namedDifferently ? (
                  //: 两个名字不同就得说清哪个是装进去的,别让人猜(原来文件夹那一层的意思在下面那句里)。
                  <span className="flex min-w-0 items-center gap-1.5 text-ui-xs text-muted-foreground" data-slot="import-skill-name">
                    <span>{t("agentSkillsImportInstalledAs")}</span>
                    <span className="break-all font-mono text-foreground">{item.name}</span>
                  </span>
                ) : null}
              </div>
              {item.folder && item.folder !== item.name ? (
                <p className="m-0 text-ui-xs text-muted-foreground">
                  {t("agentSkillsImportFolderNote").replace("{folder}", item.folder).replace("{name}", item.name)}
                </p>
              ) : null}
              {choice.include && (
                <>
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
                  {/* 一行一件事,各自占满内容宽、整行都能点 —— 不再和改名挤成两列、靠 pt-6 硬凑对齐。 */}
                  <div className="grid gap-2 text-ui-sm">
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
                </>
              )}
              <SkillContent head={item} files={item.files ?? []} />
            </section>
          );
        })}
      </div>
    </ModalShell>
  );
}
