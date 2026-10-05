import React from "react";
import { Folder, FolderOpen } from "lucide-react";

import { errorText } from "@/api/errorMessage";
import { useI18n } from "@/app/preferences";
import { ModalShell } from "@/components/app/modals";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Truncate } from "@/components/ui/truncate";
import {
  baseName,
  conflictOf,
  folderPathFrom,
  joinPath,
  notEmptyOf,
  parentOf,
  validFolderPath,
  type WorkflowFolderRow,
} from "@/features/plugins/workflowLibraryView";
import { cn } from "@/lib/utils";

/**
 * 工作流库的文件夹(ADR 0035 后续「文件夹」):文件夹就是那台 ComfyUI 上 `workflows/` 里的子目录,和它自己的侧栏同一份。
 * 这里是改它们的几个确认框 —— 新建 / 改名、删除(只删空的)、把一张工作流移到别的文件夹 —— 和拖卡片的那一点约定。
 *
 * 都和复制、改名、删除同一套规矩:先确认,写明改哪台服务器上的什么;撞名不覆盖,给一个建议名;后端现查那台机器,
 * 界面手里的列表旧了(文件夹里又有了东西、要挪的那张已经不在了)就照它说的说出来,不硬改。
 */

/** 拖一张卡片时 dataTransfer 里放的类型,值是那张工作流的路径。只有工作流库自己认它(往库上拖文件导入的那条路不认)。 */
export const WORKFLOW_DRAG_TYPE = "application/x-mosael-workflow";

export function dragWorkflow(event: React.DragEvent, path: string) {
  event.dataTransfer.setData(WORKFLOW_DRAG_TYPE, path);
  event.dataTransfer.effectAllowed = "move";
}

/** 拖着的是不是一张工作流卡片(拖过去的时候读不到值,只看得到类型)。 */
export const carriesWorkflow = (event: React.DragEvent) => Array.from(event.dataTransfer?.types ?? []).includes(WORKFLOW_DRAG_TYPE);

/**
 * 新建文件夹、文件夹改名:一个路径(相对 workflows/,可以带上级 —— 改了上级就是挪过去)。不合格的当场说、点不了;
 * 撞名(409)不合并进去,说清楚并给一个建议名。打开时选中最后一段,直接打字就是起名。
 */
export function FolderPathDialog({
  title,
  confirmLabel,
  where,
  note,
  initial,
  onSubmit,
  onClose,
}: {
  title: string;
  confirmLabel: string;
  where: string;
  /** 再多说一句(改名时:里面几张工作流跟着换路径、Mosael 里谁在用它们)。 */
  note?: string;
  initial: string;
  onSubmit: (path: string) => Promise<void>;
  onClose: () => void;
}) {
  const t = useI18n();
  const inputId = React.useId();
  const inputRef = React.useRef<HTMLInputElement>(null);
  const [value, setValue] = React.useState(initial);
  const [pending, setPending] = React.useState(false);
  const [clash, setClash] = React.useState<{ path: string; suggestion: string } | null>(null);
  const [error, setError] = React.useState("");
  const path = folderPathFrom(value);
  const bad = !validFolderPath(path);

  React.useEffect(() => {
    const frame = window.requestAnimationFrame(() => {
      const input = inputRef.current;
      if (!input) return;
      input.focus();
      input.setSelectionRange(initial.lastIndexOf("/") + 1, initial.length);
    });
    return () => window.cancelAnimationFrame(frame);
  }, [initial]);

  const submit = async () => {
    if (bad || pending) return;
    setPending(true);
    setClash(null);
    setError("");
    try {
      await onSubmit(path);
      onClose();
    } catch (failure) {
      const conflict = conflictOf(failure);
      if (conflict) setClash({ path, suggestion: conflict.suggestion });
      else setError(errorText(failure));
    } finally {
      setPending(false);
    }
  };

  return (
    <ModalShell
      open
      onOpenChange={(next) => !next && !pending && onClose()}
      title={title}
      className="w-[min(520px,calc(100vw-32px))]"
      footer={
        <>
          <Button variant="ghost" disabled={pending} onClick={onClose}>{t("cancel")}</Button>
          <Button loading={pending} disabled={bad} onClick={() => void submit()}>{confirmLabel}</Button>
        </>
      }
    >
      <div className="grid gap-3">
        <p className="m-0 text-ui-sm leading-relaxed text-muted-foreground">{where}</p>
        {note && <p className="m-0 text-ui-sm leading-relaxed text-foreground">{note}</p>}
        <div className="grid gap-1.5">
          <label htmlFor={inputId} className="text-ui-xs font-medium text-muted-foreground">{t("workflowFolderPathLabel")}</label>
          <Input
            ref={inputRef}
            id={inputId}
            aria-label={t("workflowFolderPathLabel")}
            value={value}
            onChange={(event) => {
              setValue(event.target.value);
              setClash(null);
            }}
            onKeyDown={(event) => {
              if (event.key === "Enter" && !event.nativeEvent.isComposing) void submit();
            }}
          />
          {bad && value.trim() ? (
            <p className="m-0 text-ui-xs text-destructive">{t("workflowFolderPathBad")}</p>
          ) : (
            <p className="m-0 text-ui-xs text-muted-foreground">{t("workflowFolderPathHelp")}</p>
          )}
        </div>
        {clash && (
          <div role="alert" className="grid gap-2 rounded-lg border border-warning/40 bg-panel p-3 text-ui-sm text-foreground">
            <span>{t("workflowExists").replace("{path}", clash.path)}</span>
            {clash.suggestion && (
              <span>
                <Button variant="outline" size="sm" onClick={() => { setValue(clash.suggestion); setClash(null); }}>
                  {t("workflowUseSuggestion").replace("{name}", clash.suggestion)}
                </Button>
              </span>
            )}
          </div>
        )}
        {error && <p role="alert" className="m-0 text-ui-sm text-destructive">{error}</p>}
      </div>
    </ModalShell>
  );
}

/**
 * 删除一个文件夹:只有空的才走到这里(里面有文件时菜单上点不了,说为什么)。挪进那台机器的回收目录 —— ComfyUI 删不了
 * 目录,Mosael 也不硬删。后端挪之前现查:这期间在 ComfyUI 里往里面存了东西,就不删,照实说里面有几个。
 */
export function FolderDeleteDialog({
  path,
  server,
  subfolders,
  onConfirm,
  onClose,
}: {
  path: string;
  server: string;
  /** 里面还有几个(空的)子文件夹:一起挪走,确认框里说一声。 */
  subfolders: number;
  onConfirm: () => Promise<void>;
  onClose: () => void;
}) {
  const t = useI18n();
  const [pending, setPending] = React.useState(false);
  const [error, setError] = React.useState("");
  const confirm = async () => {
    setPending(true);
    setError("");
    try {
      await onConfirm();
      onClose();
    } catch (failure) {
      const full = notEmptyOf(failure);
      setError(full ? t("workflowFolderNotEmptyNow").replace("{n}", String(full.count)) : errorText(failure));
    } finally {
      setPending(false);
    }
  };
  return (
    <ModalShell
      open
      onOpenChange={(next) => !next && !pending && onClose()}
      title={t("workflowFolderDeleteTitle").replace("{name}", path)}
      className="w-[min(480px,calc(100vw-32px))]"
      footer={
        <>
          <Button variant="ghost" disabled={pending} onClick={onClose}>{t("cancel")}</Button>
          <Button className="bg-destructive text-destructive-foreground hover:bg-destructive/90" loading={pending}
                  onClick={() => void confirm()}>
            {t("workflowFolderDeleteConfirm")}
          </Button>
        </>
      }
    >
      <div className="grid gap-3">
        <p className="m-0 text-ui-sm leading-relaxed text-muted-foreground">
          {t("workflowFolderDeleteBody").replace("{server}", server)}
          {subfolders > 0 && ` ${t("workflowFolderDeleteSubfolders").replace("{n}", String(subfolders))}`}
        </p>
        {error && <p role="alert" className="m-0 text-ui-sm text-destructive">{error}</p>}
      </div>
    </ModalShell>
  );
}

/**
 * 把一张工作流移到别的文件夹(「移动到…」,或者把卡片拖到左边的文件夹上 —— 拖过来的那个文件夹已经选好,点一下确认)。
 * 就是改它的路径:名字不变,换上级。目标文件夹里已经有同名的就不覆盖,给一个建议名。Mosael 里有地方在用它的,说一声:
 * 换了路径,它们跑的时候会说找不到这个模型(和改名、删除同一句)。
 */
export function MoveWorkflowDialog({
  path,
  label,
  folders,
  initialFolder,
  where,
  usedBy,
  onSubmit,
  onClose,
}: {
  path: string;
  label: string;
  folders: WorkflowFolderRow[];
  /** 拖到哪个文件夹上来的(`""` 是顶层);不给就停在它现在所在的那个。 */
  initialFolder?: string;
  where: string;
  /** Mosael 里在用它的地方(名字)。 */
  usedBy: string[];
  onSubmit: (newPath: string) => Promise<void>;
  onClose: () => void;
}) {
  const t = useI18n();
  const groupName = React.useId();
  const current = parentOf(path);
  const [folder, setFolder] = React.useState(initialFolder ?? current);
  const [name, setName] = React.useState(baseName(path));
  const [pending, setPending] = React.useState(false);
  const [clash, setClash] = React.useState<{ path: string; suggestion: string } | null>(null);
  const [error, setError] = React.useState("");
  const target = joinPath(folder, name);
  const unchanged = target === path;

  const submit = async () => {
    if (unchanged || pending) return;
    setPending(true);
    setClash(null);
    setError("");
    try {
      await onSubmit(target);
      onClose();
    } catch (failure) {
      const conflict = conflictOf(failure);
      if (conflict) setClash({ path: target, suggestion: conflict.suggestion });
      else setError(errorText(failure));
    } finally {
      setPending(false);
    }
  };

  const option = (value: string, text: string, depth: number) => (
    <label
      key={value || "/"}
      style={depth ? { paddingInlineStart: `${10 + depth * 14}px` } : undefined}
      className={cn(
        "flex h-8 min-w-0 cursor-pointer items-center gap-2 rounded-md px-2.5 text-ui-sm text-foreground hover:bg-secondary",
        "has-[:focus-visible]:ring-2 has-[:focus-visible]:ring-ring",
        folder === value && "bg-accent font-medium text-primary hover:bg-accent",
      )}
    >
      <input
        type="radio"
        name={groupName}
        className="sr-only"
        checked={folder === value}
        onChange={() => {
          setFolder(value);
          setClash(null);
        }}
      />
      {folder === value ? <FolderOpen size={14} aria-hidden className="shrink-0" /> : <Folder size={14} aria-hidden className="shrink-0" />}
      <Truncate className="flex-1">{text}</Truncate>
      {value === current && <span className="shrink-0 text-ui-xs font-normal text-muted-foreground">{t("workflowMoveHere")}</span>}
    </label>
  );

  return (
    <ModalShell
      open
      onOpenChange={(next) => !next && !pending && onClose()}
      title={t("workflowMoveTitle").replace("{name}", label)}
      className="w-[min(520px,calc(100vw-32px))]"
      footer={
        <>
          <Button variant="ghost" disabled={pending} onClick={onClose}>{t("cancel")}</Button>
          <Button loading={pending} disabled={unchanged} onClick={() => void submit()}>{t("workflowMoveConfirm")}</Button>
        </>
      }
    >
      <div className="grid gap-3">
        <p className="m-0 text-ui-sm leading-relaxed text-muted-foreground">{where}</p>
        <div
          role="radiogroup"
          aria-label={t("workflowMoveTo")}
          className="grid max-h-[min(320px,45dvh)] content-start gap-0.5 overflow-y-auto rounded-lg border border-border p-1"
        >
          {option("", t("workflowMoveTop"), 0)}
          {folders.map((row) => option(row.path, row.name, row.depth + 1))}
        </div>
        <p className="m-0 break-all text-ui-xs text-muted-foreground">
          {t("workflowMoveResult").replace("{path}", `workflows/${target}`)}
        </p>
        {usedBy.length > 0 && (
          <p className="m-0 text-ui-sm text-foreground">{`${t("workflowMoveUsedBy")}${usedBy.join(t("listSeparator"))}`}</p>
        )}
        {clash && (
          <div role="alert" className="grid gap-2 rounded-lg border border-warning/40 bg-panel p-3 text-ui-sm text-foreground">
            <span>{t("workflowExists").replace("{path}", clash.path)}</span>
            {clash.suggestion && (
              <span>
                <Button variant="outline" size="sm" onClick={() => {
                  setFolder(parentOf(clash.suggestion));
                  setName(baseName(clash.suggestion));
                  setClash(null);
                }}>
                  {t("workflowUseSuggestion").replace("{name}", clash.suggestion)}
                </Button>
              </span>
            )}
          </div>
        )}
        {error && <p role="alert" className="m-0 text-ui-sm text-destructive">{error}</p>}
      </div>
    </ModalShell>
  );
}
