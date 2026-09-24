import React from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Bot, Brain, ChevronDown, Pencil, Plus, Trash2, UserRound } from "lucide-react";
import { toast } from "sonner";

import { api, type Workspace } from "@/api/client";
import type { components } from "@/api/generated/schema";
import { errorText } from "@/api/errorMessage";
import { usePreferences, useI18n } from "@/app/preferences";
import { BulkActionBar, BulkCheckbox, BulkSelectTrigger, useBulkSelection } from "@/components/app/bulkSelection";
import { ConfirmDialog, DIALOG_FIELD, ModalShell } from "@/components/app/modals";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { SettingsEmpty, SettingsGroup, SettingsListBlock, SettingsListItem } from "@/components/settings/settings-layout";
import { relativeTime } from "@/lib/time";
import { formatCombo } from "@/lib/shortcuts";
import { cn } from "@/lib/utils";

type AgentMemory = components["schemas"]["AgentMemoryOut"];

/**
 * 单条记忆的字数上限,与后端 `domain/agent/memory.MAX_CONTENT_CHARS` 同一个数。
 * 后端不下发它,而超了会被 422 拒掉 —— 在输入框上先挡住、并给出计数,比存的那一下才报错好。
 */
const MAX_MEMORY_CHARS = 500;

/**
 * 跨会话记忆的可见面。
 *
 * **必须有这一页**:记忆会静默地影响此后每一次对话,而"模型到底记住了什么"是用户唯一想
 * 确认的事。只让智能体自己写、用户看不见的记忆,一旦记岔了就变成一个查不出来的幽灵 ——
 * 用户只会觉得"它最近老是自作主张",却不知道那句话是三周前自己随口说的。
 *
 * 这里读的接口和注入系统提示的是同一份(domain/agent/memory.list_memories),
 * 所以你看到的就是模型看到的。
 *
 * 版式和计价规则、音色库同一套:标题旁放「选择 / 添加」,正文是发丝线分隔的清单,
 * 添加与编辑走共享的 ModalShell,删除走 ConfirmDialog。此前这一页自成一派 —— 正文是一行
 * 裸字、来源小字贴在句尾像句子的一部分、添加区是一块常驻展开的大输入框 —— 放在设置里
 * 像另一个应用。
 */
export function AgentMemorySection({ workspace }: { workspace: Workspace }) {
  const t = useI18n();
  const qc = useQueryClient();
  /** 编辑器:`memory` 为 null 是新加一条,带 memory 的是改那一条。关的时候只收 open,不清 memory ——
   *  否则弹窗淡出的那一下标题会从「编辑记忆」跳成「添加一条记忆」。 */
  const [editor, setEditor] = React.useState<{ open: boolean; memory: AgentMemory | null }>({ open: false, memory: null });
  const closeEditor = () => setEditor((current) => ({ ...current, open: false }));
  const [deleting, setDeleting] = React.useState<AgentMemory | null>(null);
  const [bulkDeleting, setBulkDeleting] = React.useState(false);

  const queryKey = ["agent-memories", workspace.id];
  const memories = useQuery({
    queryKey,
    queryFn: () => api<AgentMemory[]>(`/api/agent/memories?workspace_id=${encodeURIComponent(workspace.id)}`),
  });
  const refresh = () => qc.invalidateQueries({ queryKey });
  const fail = (error: unknown) => toast.error(errorText(error));

  const create = useMutation({
    mutationFn: (content: string) =>
      api<AgentMemory>("/api/agent/memories", {
        method: "POST",
        body: JSON.stringify({ workspace_id: workspace.id, content, source: "user" }),
      }),
    onSuccess: () => {
      closeEditor();
      void refresh();
    },
    onError: fail,
  });
  const update = useMutation({
    mutationFn: ({ id, content }: { id: string; content: string }) =>
      api<AgentMemory>(`/api/agent/memories/${id}`, { method: "PATCH", body: JSON.stringify({ content }) }),
    onSuccess: () => {
      closeEditor();
      void refresh();
    },
    onError: fail,
  });
  const remove = useMutation({
    mutationFn: (id: string) => api(`/api/agent/memories/${id}`, { method: "DELETE" }),
    onSuccess: () => {
      setDeleting(null);
      void refresh();
    },
    onError: fail,
  });

  const rows = memories.data ?? [];
  const bulk = useBulkSelection(rows, (row) => row.id);
  const removeMany = useMutation({
    mutationFn: async (ids: string[]) => {
      // 后端没有批量删接口,逐条发、一次性回报 —— 和计价规则同一个做法,失败的几条单独说出来。
      const results = await Promise.allSettled(ids.map((id) => api(`/api/agent/memories/${id}`, { method: "DELETE" })));
      return {
        ok: results.filter((r) => r.status === "fulfilled").length,
        failed: results.filter((r) => r.status === "rejected").length,
      };
    },
    onSuccess: ({ ok, failed }) => {
      bulk.clear();
      setBulkDeleting(false);
      void refresh();
      if (failed) toast.error(t("bulkPartialFailed").replace("{ok}", String(ok)).replace("{failed}", String(failed)));
      else toast.success(t("bulkDeleteDone").replace("{n}", String(ok)));
    },
    onError: fail,
  });

  const userCount = rows.filter((row) => row.source === "user").length;
  const openAdd = () => setEditor({ open: true, memory: null });
  const editing = editor.memory;

  return (
    <SettingsGroup
      title={t("agentMemoryTitle")}
      description={t("agentMemoryDesc")}
      contentClassName={memories.data && rows.length === 0 ? "min-h-0" : undefined}
      actions={
        <div className="flex items-center gap-1.5">
          <BulkSelectTrigger active={bulk.active} onEnter={bulk.enter} disabled={rows.length === 0} />
          <Button variant="outline" size="sm" onClick={openAdd}>
            <Plus size={13} /> {t("agentMemoryAdd")}
          </Button>
        </div>
      }
    >
      <MemoryEditorDialog
        open={editor.open}
        title={editing ? t("agentMemoryEdit") : t("agentMemoryAddTitle")}
        initialValue={editing?.content ?? ""}
        pending={create.isPending || update.isPending}
        onCancel={closeEditor}
        onSubmit={(content) => {
          if (editing) update.mutate({ id: editing.id, content });
          else create.mutate(content);
        }}
      />
      <ConfirmDialog
        open={deleting !== null}
        title={t("agentMemoryDeleteTitle")}
        // 把那句话原样念出来:同一页里常有几条长得很像的约定,只说"删除这一条"容易删错。
        body={t("agentMemoryDeleteBody").replace("{content}", clip(deleting?.content ?? "", 80))}
        confirmLabel={t("delete")}
        pending={remove.isPending}
        onCancel={() => setDeleting(null)}
        onConfirm={() => deleting && remove.mutate(deleting.id)}
      />
      <ConfirmDialog
        open={bulkDeleting}
        title={t("bulkDeleteConfirm").replace("{n}", String(bulk.count))}
        body={t("bulkDeleteConfirmBody").replace("{n}", String(bulk.count))}
        confirmLabel={t("delete")}
        pending={removeMany.isPending}
        onCancel={() => setBulkDeleting(false)}
        onConfirm={() => removeMany.mutate(bulk.selectedIds)}
      />

      {memories.isError ? (
        // 读失败要说出来,不能落进"还没有记忆"—— 那会让人以为记忆全丢了。
        <SettingsEmpty
          icon={<Brain size={20} />}
          title={t("pageLoadError")}
          body={errorText(memories.error)}
          action={
            <Button variant="secondary" onClick={() => void memories.refetch()}>
              {t("retry")}
            </Button>
          }
        />
      ) : memories.data && rows.length === 0 ? (
        // 空态要说清**记忆是拿来干什么的**,并把「添加」递到手边 —— 标题旁那颗按钮离这里半屏远。
        <SettingsEmpty
          icon={<Brain size={20} />}
          title={t("agentMemoryEmpty")}
          body={t("agentMemoryEmptyHint")}
          action={
            <Button variant="outline" size="sm" onClick={openAdd}>
              <Plus size={13} /> {t("agentMemoryAdd")}
            </Button>
          }
        />
      ) : rows.length > 0 ? (
        <SettingsListBlock
          toolbar={
            bulk.active ? (
              <BulkActionBar
                active={bulk.active}
                count={bulk.count}
                allSelected={bulk.allSelected}
                onToggleAll={bulk.toggleAll}
                onExit={bulk.exit}
              >
                <Button variant="outline" size="sm" loading={removeMany.isPending} onClick={() => setBulkDeleting(true)}>
                  <Trash2 size={12} /> {t("bulkDelete")}
                </Button>
              </BulkActionBar>
            ) : (
              // 一眼看到"有多少、各是谁写的":用户写的会排在前面注入,总量超出时先保住它们。
              <p className="m-0 text-ui-xs tabular-nums text-muted-foreground">
                {t("agentMemorySummary")
                  .replace("{n}", String(rows.length))
                  .replace("{user}", String(userCount))
                  .replace("{agent}", String(rows.length - userCount))}
              </p>
            )
          }
        >
          {rows.map((row) => (
            <MemoryRow
              key={row.id}
              memory={row}
              selecting={bulk.active}
              selected={bulk.isSelected(row.id)}
              onToggleSelected={(event) => bulk.toggle(row.id, event)}
              onEdit={() => setEditor({ open: true, memory: row })}
              onDelete={() => setDeleting(row)}
            />
          ))}
        </SettingsListBlock>
      ) : null}
    </SettingsGroup>
  );
}

/**
 * 清单里的一条。
 *
 * 三格:正文(常规字重,可多行,超过三行夹住、给「展开」)、元信息一行(来源徽标 · 时间)、
 * 行尾动作。来源是**元信息**,不是句子的一部分 —— 此前它是贴在句尾的一截浅色小字,
 * 读起来像"成片统一竖屏智能体记的"。
 *
 * 动作平时收起、悬停或键盘聚焦到这一行时出现:一列常驻的铅笔和垃圾桶会把清单读成一张操作表。
 * 没有悬停的设备(触屏)上常显,否则那里根本点不到。
 */
function MemoryRow({
  memory,
  selecting,
  selected,
  onToggleSelected,
  onEdit,
  onDelete,
}: {
  memory: AgentMemory;
  selecting: boolean;
  selected: boolean;
  onToggleSelected: (event: { shiftKey?: boolean }) => void;
  onEdit: () => void;
  onDelete: () => void;
}) {
  const t = useI18n();
  const { locale } = usePreferences();
  const [expanded, setExpanded] = React.useState(false);
  const { ref, clipped } = useClipped<HTMLParagraphElement>(memory.content);
  const fromAgent = memory.source !== "user";
  const edited = wasEdited(memory);
  const stamp = edited ? memory.updated_at : memory.created_at;

  return (
    <SettingsListItem
      data-source={memory.source}
      className={cn(
        "group/memory grid items-start gap-3 py-4",
        selecting ? "grid-cols-[auto_minmax(0,1fr)]" : "grid-cols-[minmax(0,1fr)_auto]",
        selected && "rounded-md bg-[color-mix(in_srgb,var(--primary)_7%,transparent)]",
      )}
    >
      {selecting && <BulkCheckbox checked={selected} onToggle={onToggleSelected} label={t("bulkSelectRow")} />}
      <div className="grid min-w-0 grid-cols-[minmax(0,1fr)] gap-1.5">
        <p
          ref={ref}
          className={cn(
            "m-0 whitespace-pre-wrap break-words text-ui-md leading-[1.6] text-foreground",
            !expanded && "line-clamp-3",
          )}
        >
          {memory.content}
        </p>
        <div className="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1 text-ui-xs text-muted-foreground">
          <span
            data-slot="memory-source"
            className={cn(
              "inline-flex items-center gap-1 rounded-sm px-1.5 py-px text-ui-2xs font-medium [&_svg]:size-3",
              // 智能体记的那几条才是要人过目的(记岔了的就在它们里面),所以它们着主色;人自己写的走中性色。
              fromAgent
                ? "bg-[color-mix(in_oklab,var(--primary)_14%,transparent)] text-primary"
                : "bg-secondary text-secondary-foreground",
            )}
          >
            {fromAgent ? <Bot aria-hidden /> : <UserRound aria-hidden />}
            {fromAgent ? t("agentMemoryFromAgent") : t("agentMemoryFromUser")}
          </span>
          <time dateTime={stamp} title={absoluteTime(stamp, locale)}>
            {t(edited ? "agentMemoryEditedAt" : "agentMemoryAddedAt").replace("{time}", relativeTime(stamp, locale))}
          </time>
          {(clipped || expanded) && (
            <button
              type="button"
              aria-expanded={expanded}
              className="inline-flex cursor-pointer items-center gap-0.5 rounded-sm border-0 bg-transparent p-0 text-ui-xs font-medium text-primary hover:underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              onClick={() => setExpanded((value) => !value)}
            >
              {expanded ? t("collapse") : t("expand")}
              <ChevronDown size={12} className={cn("transition-transform", expanded && "rotate-180")} aria-hidden />
            </button>
          )}
        </div>
      </div>
      {!selecting && (
        <div
          data-slot="memory-actions"
          className="flex items-center gap-1 opacity-0 transition-opacity group-hover/memory:opacity-100 group-focus-within/memory:opacity-100 [@media(hover:none)]:opacity-100"
        >
          <Button variant="ghost" size="icon-sm" aria-label={t("agentMemoryEdit")} title={t("agentMemoryEdit")} onClick={onEdit}>
            <Pencil size={13} />
          </Button>
          <Button
            variant="ghost"
            size="icon-sm"
            className="hover:text-destructive"
            aria-label={t("delete")}
            title={t("delete")}
            onClick={onDelete}
          >
            <Trash2 size={13} />
          </Button>
        </div>
      )}
    </SettingsListItem>
  );
}

/**
 * 添加 / 编辑共用的编辑器。走 ModalShell —— 和计价规则、音色库同一种"点按钮 → 弹窗 → 取消/保存"。
 *
 * ⌘/Ctrl+Enter 保存(多行输入里 Enter 要留给换行),Esc 由弹窗本身关掉。
 * 输入法正在组字时不接 Enter —— 否则选词的那一下就被当成提交。
 */
function MemoryEditorDialog({
  open,
  title,
  initialValue,
  pending,
  onCancel,
  onSubmit,
}: {
  open: boolean;
  title: string;
  initialValue: string;
  pending: boolean;
  onCancel: () => void;
  onSubmit: (content: string) => void;
}) {
  const t = useI18n();
  const formId = React.useId();
  const fieldId = React.useId();
  const [draft, setDraft] = React.useState(initialValue);
  /** 打开后第一次聚焦把光标放到末尾 —— 改一条记忆多半是在句尾补一句,光标停在句首要先按一下 End。 */
  const caretPlaced = React.useRef(false);
  React.useEffect(() => {
    if (!open) return;
    setDraft(initialValue);
    caretPlaced.current = false;
  }, [open, initialValue]);

  const content = draft.trim();
  const unchanged = initialValue !== "" && content === initialValue.trim();
  const canSave = content.length > 0 && !unchanged && !pending;
  const submit = () => {
    if (canSave) onSubmit(content);
  };

  return (
    <ModalShell
      open={open}
      onOpenChange={(next) => !next && !pending && onCancel()}
      title={title}
      className="w-[480px]"
      footer={
        <>
          <Button type="button" variant="outline" disabled={pending} onClick={onCancel}>
            {t("cancel")}
          </Button>
          <Button type="submit" form={formId} disabled={!canSave} loading={pending}>
            {t("save")}
          </Button>
        </>
      }
    >
      <form
        id={formId}
        className="grid"
        onSubmit={(event) => {
          event.preventDefault();
          submit();
        }}
      >
        <label className={DIALOG_FIELD} htmlFor={fieldId}>
          <span id={`${fieldId}-label`}>{t("agentMemoryContentLabel")}</span>
          <Textarea
            id={fieldId}
            aria-labelledby={`${fieldId}-label`}
            aria-describedby={`${fieldId}-hint`}
            rows={4}
            autoFocus
            value={draft}
            maxLength={MAX_MEMORY_CHARS}
            placeholder={t("agentMemoryPlaceholder")}
            onChange={(event) => setDraft(event.target.value)}
            onFocus={(event) => {
              if (caretPlaced.current) return;
              caretPlaced.current = true;
              const end = event.currentTarget.value.length;
              event.currentTarget.setSelectionRange(end, end);
            }}
            onKeyDown={(event) => {
              if (event.key !== "Enter" || !(event.metaKey || event.ctrlKey) || event.nativeEvent.isComposing) return;
              event.preventDefault();
              submit();
            }}
          />
          <small id={`${fieldId}-hint`} className="flex items-start justify-between gap-3">
            <span>{t("agentMemoryFieldHint")}</span>
            <span className="shrink-0 whitespace-nowrap tabular-nums">
              {t("agentMemorySaveShortcut").replace("{combo}", formatCombo("Mod+Enter"))} · {draft.length} / {MAX_MEMORY_CHARS}
            </span>
          </small>
        </label>
      </form>
    </ModalShell>
  );
}

/**
 * 正文是不是真的被夹住了。只在夹住时才给「展开」—— 一句短话后面跟个展开按钮,点下去什么也不变。
 * 量的是渲染结果(scrollHeight 比 clientHeight 高),不按字数猜:同样 80 个字,中英文、窄宽窗口折出来的行数都不一样。
 */
function useClipped<T extends HTMLElement>(content: string) {
  const ref = React.useRef<T>(null);
  const [clipped, setClipped] = React.useState(false);
  React.useLayoutEffect(() => {
    const node = ref.current;
    if (!node) return;
    const measure = () => setClipped(node.scrollHeight > node.clientHeight + 1);
    measure();
    if (typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(measure);
    observer.observe(node);
    return () => observer.disconnect();
  }, [content]);
  return { ref, clipped };
}

/** 后端两个时间戳各自取一次 now(),新建的那一条也会差几微秒 —— 差出一秒以上才算改过。 */
function wasEdited(memory: AgentMemory): boolean {
  return toDate(memory.updated_at).getTime() - toDate(memory.created_at).getTime() > 1000;
}

/** 后端时间是不带时区的 UTC ISO 串(见 lib/time.relativeTime)。 */
function toDate(iso: string): Date {
  return new Date(/Z|[+-]\d\d:?\d\d$/.test(iso) ? iso : `${iso}Z`);
}

function absoluteTime(iso: string, locale: string): string {
  return toDate(iso).toLocaleString(locale, { dateStyle: "medium", timeStyle: "short" });
}

function clip(text: string, max: number): string {
  const flat = text.replace(/\s+/g, " ").trim();
  return flat.length > max ? `${flat.slice(0, max)}…` : flat;
}
