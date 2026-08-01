import React from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Brain, Plus, Trash2 } from "lucide-react";
import { toast } from "sonner";

import { api, type Workspace } from "@/api/client";
import type { components } from "@/api/generated/schema";
import { useI18n } from "@/app/preferences";
import { BulkActionBar, BulkCheckbox, useBulkSelection } from "@/components/app/bulkSelection";
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
    <SettingsGroup title={t("agentMemoryTitle")} description={t("agentMemoryDesc")}>
      <SettingsBlock>
        <div className="grid gap-1.5">
          <BulkActionBar count={bulk.count} allSelected={bulk.allSelected} onToggleAll={bulk.toggleAll} onClear={bulk.clear}>
            <Button variant="outline" size="sm" disabled={removeMany.isPending} onClick={() => removeMany.mutate(bulk.selectedIds)}>
              <Trash2 size={12} /> {t("bulkDelete")}
            </Button>
          </BulkActionBar>

          {rows.map((row) => (
            <div
              className={cn(
                "grid grid-cols-[auto_28px_minmax(0,1fr)_auto] items-start gap-2 rounded-md border border-border bg-panel px-2 py-1.5",
                bulk.isSelected(row.id) && "border-primary/45 bg-[color-mix(in_srgb,var(--primary)_5%,var(--panel))]",
              )}
              key={row.id}
            >
              <BulkCheckbox
                checked={bulk.isSelected(row.id)}
                onToggle={(event) => bulk.toggle(row.id, event)}
                label={t("bulkSelectRow")}
              />
              <span className="mt-0.5 grid h-7 w-7 place-items-center rounded-md bg-accent text-accent-foreground">
                <Brain size={13} />
              </span>
              <div className="grid min-w-0 gap-1">
                {editing?.id === row.id ? (
                  <>
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
                  </>
                ) : (
                  <>
                    {/* 点正文即改 —— 记忆是要被修的东西(模型记岔了是常态),多一个铅笔图标只是多一次瞄准。 */}
                    <button
                      type="button"
                      className="cursor-pointer border-0 bg-transparent p-0 text-left text-[12.5px] leading-[1.5] text-foreground"
                      onClick={() => setEditing({ id: row.id, content: row.content })}
                    >
                      {row.content}
                    </button>
                    <span className="text-[10.5px] text-muted-foreground">
                      {row.source === "user" ? t("agentMemoryFromUser") : t("agentMemoryFromAgent")}
                    </span>
                  </>
                )}
              </div>
              <Button variant="ghost" size="icon" aria-label={t("delete")} onClick={() => remove.mutate(row.id)}>
                <Trash2 size={13} />
              </Button>
            </div>
          ))}

          {rows.length === 0 && !memories.isPending && (
            <p className="m-0 text-xs leading-[1.5] text-muted-foreground">{t("agentMemoryEmpty")}</p>
          )}

          <div className="grid gap-1.5 rounded-md border border-dashed border-border px-2 py-2">
            <Textarea
              rows={2}
              value={draft}
              placeholder={t("agentMemoryPlaceholder")}
              maxLength={500}
              onChange={(event) => setDraft(event.target.value)}
            />
            <div className="flex justify-end">
              <Button
                size="sm"
                disabled={!draft.trim() || create.isPending}
                onClick={() => create.mutate(draft.trim())}
              >
                <Plus size={12} /> {t("agentMemoryAdd")}
              </Button>
            </div>
          </div>
        </div>
      </SettingsBlock>
    </SettingsGroup>
  );
}
