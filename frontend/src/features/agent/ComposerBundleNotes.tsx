import React from "react";
import { FileX, Sparkles, X } from "lucide-react";

import type { AgentBundleSkipped, AgentSkillImport } from "@/api/client";
import type { MessageKey } from "@/app/messages";
import { useI18n } from "@/app/preferences";
import { Button } from "@/components/ui/button";
import { IconButton } from "@/components/ui/icon-button";
import { Truncate } from "@/components/ui/truncate";
import { SkillImportDialog } from "@/features/agent/skills/SkillImportDialog";

/**
 * 对话里附上的压缩包 / 文件夹解开之后,要人看一眼的两种情况(ADR 0059),摆在输入卡里、附件条上面:
 *
 * - **发现了技能**:「发现 N 个技能,安装到工作区?」点「查看并安装」打开的就是设置页那个导入审阅(SkillImportDialog,
 *   同一份暂存、同一套校验和撞名处理),确认了才装;「忽略」只是收起这张卡,什么都没装过。
 * - **有文件没收**:逐个列出是哪个、为什么(不是文本也不是图片、太大、超个数)—— 不静默丢掉。
 */

export interface BundleNote {
  id: string;
  sourceName: string;
  skillImport: AgentSkillImport | null;
  skipped: AgentBundleSkipped[];
}

/** 没收的文件摆几行;再多的折成「还有 N 个」,不把输入框顶出屏幕。 */
const SHOWN_SKIPPED = 6;

const SKIP_REASON: Record<AgentBundleSkipped["reason"], MessageKey> = {
  unsupported: "composerSkipUnsupported",
  too_large: "composerSkipTooLarge",
  too_many: "composerSkipTooMany",
};

const NOTE = "flex items-start gap-2 rounded-md border border-border bg-secondary px-2.5 py-1.5 text-ui-xs text-foreground";

export function ComposerBundleNotes({
  workspaceId,
  notes,
  onDismiss,
}: {
  workspaceId: string;
  notes: BundleNote[];
  onDismiss: (id: string) => void;
}) {
  const t = useI18n();
  const [reviewing, setReviewing] = React.useState<BundleNote | null>(null);

  return (
    <>
      {notes.length > 0 && (
        <div className="grid gap-1 pb-1.5">
          {notes.map((note) =>
            note.skillImport ? (
              <div key={note.id} role="status" className={NOTE}>
                <Sparkles size={13} className="mt-0.5 shrink-0 text-primary" aria-hidden />
                <div className="grid min-w-0 flex-1 gap-0.5">
                  <span className="font-medium">
                    {t("composerBundleSkills").replace("{name}", note.sourceName).replace("{n}", String(note.skillImport.skills.length))}
                  </span>
                  <Truncate className="text-muted-foreground">
                    {note.skillImport.skills.map((item) => item.title || item.name).join("、")}
                  </Truncate>
                </div>
                <div className="flex shrink-0 items-center gap-1">
                  <Button size="xs" variant="outline" onClick={() => setReviewing(note)}>
                    {t("composerBundleReview")}
                  </Button>
                  <Button size="xs" variant="ghost" onClick={() => onDismiss(note.id)}>
                    {t("composerBundleDismiss")}
                  </Button>
                </div>
              </div>
            ) : (
              <div key={note.id} role="status" className={NOTE}>
                <FileX size={13} className="mt-0.5 shrink-0 text-muted-foreground" aria-hidden />
                <div className="grid min-w-0 flex-1 gap-0.5">
                  <span className="font-medium">
                    {t("composerBundleSkipped").replace("{name}", note.sourceName).replace("{n}", String(note.skipped.length))}
                  </span>
                  <ul className="m-0 grid list-none gap-0 p-0 text-muted-foreground">
                    {note.skipped.slice(0, SHOWN_SKIPPED).map((one) => (
                      <Truncate as="li" key={one.path}>
                        {one.path} · {t(SKIP_REASON[one.reason])}
                      </Truncate>
                    ))}
                    {note.skipped.length > SHOWN_SKIPPED && (
                      <li>{t("composerBundleMore").replace("{n}", String(note.skipped.length - SHOWN_SKIPPED))}</li>
                    )}
                  </ul>
                </div>
                <IconButton size="icon-xs" label={t("composerBundleClose")} onClick={() => onDismiss(note.id)}>
                  <X size={12} />
                </IconButton>
              </div>
            ),
          )}
        </div>
      )}
      <SkillImportDialog
        workspaceId={workspaceId}
        staged={reviewing?.skillImport ?? null}
        onClose={() => setReviewing(null)}
        //: 装好了这张卡就完成了使命;只是关掉审阅(没装)的话卡还在,随时能再点开。
        onInstalled={() => reviewing && onDismiss(reviewing.id)}
      />
    </>
  );
}
