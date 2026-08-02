import React from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Plus, Trash2 } from "lucide-react";
import { toast } from "sonner";

import { api, type Workspace } from "@/api/client";
import type { components } from "@/api/generated/schema";
import { useI18n } from "@/app/preferences";
import { BulkActionBar, BulkCheckbox, BulkSelectTrigger, useBulkSelection } from "@/components/app/bulkSelection";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { SettingsBlock, SettingsGroup } from "@/features/settings/ui";
import { cn } from "@/lib/utils";

type AgentMemory = components["schemas"]["AgentMemoryOut"];

/**
 * 跨会话记忆的可见面。
 *
 * **必须有这一页**:记忆会静默地影响此后每一次对话,而"模型到底记住了什么"是用户唯一想
 * 确认的事。只让智能体自己写、用户看不见的记忆,一旦记岔了就变成一个查不出来的幽灵 ——
 * 用户只会觉得"它最近老是自作主张",却不知道那句话是三周前自己随口说的。
 *
 * 这里读的接口和注入系统提示的是同一份(domain/agent/memory.list_memories),
 * 所以你看到的就是模型看到的。
 */
export function AgentMemorySection({ workspace }: { workspace: Workspace }) {
  const t = useI18n();
  const qc = useQueryClient();
  const [draft, setDraft] = React.useState("");
  const [editing, setEditing] = React.useState<{ id: string; content: string } | null>(null);
  const [adding, setAdding] = React.useState(false);

  const memories = useQuery({
    queryKey: ["agent-memories", workspace.id],
    queryFn: () => api<AgentMemory[]>(`/api/agent/memories?workspace_id=${encodeURIComponent(workspace.id)}`),
  });
  const refresh = () => qc.invalidateQueries({ queryKey: ["agent-memories", workspace.id] });
  const fail = (error: unknown) => toast.error(error instanceof Error ? error.message : String(error));

  const create = useMutation({
    mutationFn: (content: string) =>
      api<AgentMemory>("/api/agent/memories", {
        method: "POST",
        body: JSON.stringify({ workspace_id: workspace.id, content, source: "user" }),
      }),
    onSuccess: () => {
      setDraft("");
      setAdding(false);
      void refresh();
    },
    onError: fail,
  });
  const update = useMutation({
    mutationFn: ({ id, content }: { id: string; content: string }) =>
      api<AgentMemory>(`/api/agent/memories/${id}`, { method: "PATCH", body: JSON.stringify({ content }) }),
    onSuccess: () => {
      setEditing(null);
      void refresh();
    },
    onError: fail,
  });
  const remove = useMutation({
    mutationFn: (id: string) => api(`/api/agent/memories/${id}`, { method: "DELETE" }),
    onSuccess: refresh,
    onError: fail,
  });
  const removeMany = useMutation({
    mutationFn: async (ids: string[]) => {
      await Promise.allSettled(ids.map((id) => api(`/api/agent/memories/${id}`, { method: "DELETE" })));
    },
    onSuccess: () => {
      bulk.clear();
      void refresh();
    },
  });

  const rows = memories.data ?? [];
  const bulk = useBulkSelection(rows, (row) => row.id);

  return (
    <SettingsGroup
      title={t("agentMemoryTitle")}
      description={t("agentMemoryDesc")}
      actions={
        <div className="flex items-center gap-1.5">
          <BulkSelectTrigger active={bulk.active} onEnter={bulk.enter} disabled={rows.length === 0} />
          <Button variant="outline" size="sm" onClick={() => setAdding(true)} disabled={adding}>
            <Plus size={13} /> {t("agentMemoryAdd")}
          </Button>
        </div>
      }
    >
      {/* **一条记忆就是一行字**,不该是一个盒子里套一个盒子。此前每条外面一个卡片、
          里面还有图标块和来源标签,加上底部一整块虚线添加区 —— 三层框住的其实只是
          一句话。现在:发丝线分隔的清单,点哪行改哪行;来源做成行尾的浅色小字。 */}
      <SettingsBlock>
        <div className="grid gap-1.5">
          <BulkActionBar
            active={bulk.active}
            count={bulk.count}
            allSelected={bulk.allSelected}
            onToggleAll={bulk.toggleAll}
            onExit={bulk.exit}
          >
            <Button variant="outline" size="sm" disabled={removeMany.isPending} onClick={() => removeMany.mutate(bulk.selectedIds)}>
              <Trash2 size={12} /> {t("bulkDelete")}
            </Button>
          </BulkActionBar>

          {rows.length > 0 && (
            <ul className="m-0 grid list-none gap-px p-0">
              {rows.map((row) => (
                <li
                  className={cn(
                    "group grid min-w-0 items-start gap-2 border-b border-border/45 py-1.5 last:border-b-0",
                    bulk.active ? "grid-cols-[auto_minmax(0,1fr)_auto]" : "grid-cols-[minmax(0,1fr)_auto]",
                    bulk.isSelected(row.id) && "bg-[color-mix(in_srgb,var(--primary)_5%,transparent)]",
                  )}
                  key={row.id}
                >
                  {bulk.active && (
                    <BulkCheckbox
                      checked={bulk.isSelected(row.id)}
                      onToggle={(event) => bulk.toggle(row.id, event)}
                      label={t("bulkSelectRow")}
                    />
                  )}
                  {editing?.id === row.id ? (
                    <div className="grid min-w-0 gap-1.5">
                      <Textarea
                        rows={2}
                        autoFocus
                        value={editing.content}
                        onChange={(event) => setEditing({ id: row.id, content: event.target.value })}
                      />
                      <div className="flex gap-1.5">
                        <Button
                          size="sm"
                          disabled={update.isPending || !editing.content.trim()}
                          onClick={() => update.mutate({ id: row.id, content: editing.content })}
                        >
                          {t("agentMemorySave")}
                        </Button>
                        <Button variant="ghost" size="sm" onClick={() => setEditing(null)}>
                          {t("cancel")}
                        </Button>
                      </div>
                    </div>
                  ) : (
                    // 点正文即改 —— 记忆是要被修的东西(模型记岔了是常态),多一个铅笔图标只是多一次瞄准。
                    <button
                      type="button"
                      className="min-w-0 cursor-pointer border-0 bg-transparent p-0 text-left text-[12.5px] leading-[1.55] text-foreground"
                      onClick={() => setEditing({ id: row.id, content: row.content })}
                    >
                      {row.content}
                      <span className="ml-1.5 whitespace-nowrap text-[10.5px] text-muted-foreground">
                        {row.source === "user" ? t("agentMemoryFromUser") : t("agentMemoryFromAgent")}
                      </span>
                    </button>
                  )}
                  {/* 删除按钮平时隐形,悬停/聚焦才出现:一列常驻的垃圾桶会把清单读成一张操作表。 */}
                  <Button
                    variant="ghost"
                    size="icon"
                    className="h-7 w-7 opacity-0 transition-opacity group-hover:opacity-100 focus-visible:opacity-100"
                    aria-label={t("delete")}
                    loading={remove.isPending && remove.variables === row.id}
                    onClick={() => remove.mutate(row.id)}
                  >
                    <Trash2 size={13} />
                  </Button>
                </li>
              ))}
            </ul>
          )}

          {rows.length === 0 && !memories.isPending && !adding && (
            <p className="m-0 text-xs leading-[1.55] text-muted-foreground">{t("agentMemoryEmpty")}</p>
          )}

          {/* 添加区只在要添加时出现 —— 常驻一个空输入框会让"还没有记忆"这件事被一个大框盖住。 */}
          {adding && (
            <div className="grid gap-1.5 pt-1">
              <Textarea
                rows={2}
                autoFocus
                value={draft}
                placeholder={t("agentMemoryPlaceholder")}
                maxLength={500}
                onChange={(event) => setDraft(event.target.value)}
              />
              <div className="flex gap-1.5">
                <Button size="sm" disabled={!draft.trim() || create.isPending} onClick={() => create.mutate(draft.trim())}>
                  {t("agentMemorySave")}
                </Button>
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => {
                    setAdding(false);
                    setDraft("");
                  }}
                >
                  {t("cancel")}
                </Button>
              </div>
            </div>
          )}
        </div>
      </SettingsBlock>
    </SettingsGroup>
  );
}
