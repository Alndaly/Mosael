import React from "react";
import { ChevronRight, FileCode2, FileText, FileWarning } from "lucide-react";

import { useI18n } from "@/app/preferences";
import { InlineMarkdown } from "@/components/markdown/InlineMarkdown";
import { Truncate } from "@/components/ui/truncate";
import { cn } from "@/lib/utils";

/** 技能里的一个文件,审阅要看的那些(导入暂存和已装的技能是同一个形状)。 */
export interface SkillContentFile {
  path: string;
  size: number;
  script?: boolean;
  text?: string | null;
  binary?: boolean;
}

/** 审阅时头上要摆出来的那几样。 */
export interface SkillContentHead {
  description: string;
  license?: string;
  compatibility?: string;
  allowed_tools?: string;
  unknown_fields?: string[];
}

export function formatBytes(size: number): string {
  if (size < 1024) return `${size} B`;
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(1)} KB`;
  return `${(size / 1024 / 1024).toFixed(1)} MB`;
}

/**
 * 一个技能的**全部内容**(ADR 0040 §6:启用之前给人看全文)。
 *
 * 头:说明、许可证、环境要求,以及两件要特别说清的事 —— 它声明的 `allowed-tools`(Mosael 不因此批准任何东西)、
 * Mosael 不用的字段。下面是每个文件:文本给全文(SKILL.md 默认展开,别的点开看),二进制只说大小,脚本标「不会执行」。
 *
 * 文件内容按**纯文本**摆,不渲染 Markdown:审阅要看的是它真正写了什么,渲染会把注释、链接目标、HTML 藏起来。
 */
export function SkillContent({ head, files }: { head: SkillContentHead; files: readonly SkillContentFile[] }) {
  const t = useI18n();
  return (
    <div className="grid min-w-0 gap-3" data-slot="skill-content">
      <dl className="m-0 grid grid-cols-[auto_minmax(0,1fr)] gap-x-3 gap-y-1 text-ui-xs">
        <dt className="text-muted-foreground">{t("agentSkillsFieldDescription")}</dt>
        <dd className="m-0 whitespace-pre-wrap text-foreground">
          <InlineMarkdown text={head.description} links={false} />
        </dd>
        {head.license ? (
          <>
            <dt className="text-muted-foreground">{t("agentSkillsFieldLicense")}</dt>
            <dd className="m-0 text-foreground">{head.license}</dd>
          </>
        ) : null}
        {head.compatibility ? (
          <>
            <dt className="text-muted-foreground">{t("agentSkillsFieldCompatibility")}</dt>
            <dd className="m-0 text-foreground">{head.compatibility}</dd>
          </>
        ) : null}
      </dl>
      {head.allowed_tools ? (
        <p className="m-0 text-ui-xs text-warning" data-slot="skill-allowed-tools">
          {t("agentSkillsAllowedTools").replace("{tools}", head.allowed_tools)}
        </p>
      ) : null}
      {(head.unknown_fields?.length ?? 0) > 0 ? (
        <p className="m-0 text-ui-xs text-muted-foreground" data-slot="skill-unknown-fields">
          {t("agentSkillsUnknownFields").replace("{fields}", (head.unknown_fields ?? []).join("、"))}
        </p>
      ) : null}
      <div className="grid min-w-0 gap-1">
        <span className="text-ui-xs font-medium text-muted-foreground">{t("agentSkillsFiles")}</span>
        {files.map((file) => (
          <FileEntry key={file.path} file={file} />
        ))}
      </div>
    </div>
  );
}

function FileEntry({ file }: { file: SkillContentFile }) {
  const t = useI18n();
  const readable = typeof file.text === "string";
  const [open, setOpen] = React.useState(file.path === "SKILL.md");
  const Icon = file.binary ? FileWarning : file.script ? FileCode2 : FileText;
  return (
    <div className="min-w-0" data-skill-file={file.path}>
      <button
        type="button"
        disabled={!readable}
        aria-expanded={readable ? open : undefined}
        className={cn(
          "flex w-full min-w-0 items-center gap-1.5 rounded-md border-0 bg-transparent px-1 py-1 text-left text-ui-xs",
          readable && "cursor-pointer hover:bg-muted",
        )}
        onClick={() => readable && setOpen((value) => !value)}
      >
        {readable ? (
          <ChevronRight size={12} className={cn("shrink-0 transition-transform", open && "rotate-90")} aria-hidden />
        ) : (
          <span className="w-3 shrink-0" aria-hidden />
        )}
        <Icon size={12} className="shrink-0 text-muted-foreground" aria-hidden />
        <Truncate className="min-w-0 flex-1 font-mono text-foreground">{file.path}</Truncate>
        {file.script && (
          <span className="shrink-0 rounded-sm bg-[color-mix(in_srgb,var(--warning)_14%,transparent)] px-1 text-ui-2xs text-warning">
            {t("agentSkillsScriptBadge")}
          </span>
        )}
        <span className="shrink-0 tabular-nums text-muted-foreground">
          {file.binary ? t("agentSkillsBinary").replace("{size}", formatBytes(file.size)) : formatBytes(file.size)}
        </span>
      </button>
      {open && readable && (
        <pre className="m-0 ml-5 max-h-[320px] overflow-auto whitespace-pre-wrap break-words rounded-md border border-border bg-panel px-2 py-1.5 font-mono text-ui-xs leading-[1.5] text-foreground">
          {file.text}
        </pre>
      )}
    </div>
  );
}
