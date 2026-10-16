/**
 * 工作流触发器面板(ADR 0065):**谁在哪个群、丢来什么样的消息,就让这张工作流跑一次**。
 *
 * 入口放哪、为什么:**工作流卡片右上角的 ⋯ 菜单里一行「触发器」**(见 WorkflowsView)。
 * 理由:触发器属于**某一条工作流**,而工作流卡片就是"这一条"的身份所在 —— 编辑器画布是改图的地方,
 * 往里塞一个改"这张图怎么被叫起来"的面板会让人以为它也是图的一部分(它不是,ADR 0065 §1)。
 * 卡片菜单加一行是最小的一步:不新增页面、不新增导航项,不想要它的人一辈子不会点开。
 *
 * 这一个弹窗把三件事放在一起,因为用户问的其实是同一个问题"它在干活吗":
 * 列出手上这条工作流的触发器(带开关)、新建/改一条、以及每条**最近触发过哪些消息、起了哪次运行**。
 */

import React from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { History, Play, Plus, Trash2, Zap } from "lucide-react";
import { toast } from "sonner";

import {
  createWorkflowTrigger,
  deleteWorkflowTrigger,
  listWorkflowTriggerEvents,
  listWorkflowTriggers,
  updateWorkflowTrigger,
  type WorkflowTrigger,
} from "@/api/client";
import { api } from "@/api/transport";
import { usePreferences } from "@/app/preferences";
import { ConfirmDialog, ModalShell } from "@/components/app/modals";
import { FailureCard } from "@/components/failure/FailureCard";
import { EmptyState } from "@/components/layout/EmptyState";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Skeleton } from "@/components/ui/skeleton";
import { Switch } from "@/components/ui/switch";
import { Truncate } from "@/components/ui/truncate";
import { gotoJob } from "@/lib/deepLink";
import { cn } from "@/lib/utils";
import {
  eventTone,
  formatKeywords,
  parseKeywords,
  startParamNamesOf,
  TRIGGER_FIELD_OPTIONS,
  TRIGGER_TYPE_OPTIONS,
  triggerSummary,
  withParamMapping,
} from "./workflowTriggers";

/** 只取这两格:面板要的是一个能选的下拉(名字 + id)。 */
type BotLite = { id: string; name: string };

type Draft = {
  name: string;
  message_types: string[];
  keywords: string;
  bot_id: string;
  chat_id: string;
  params: Record<string, string>;
  reply_in_chat: boolean;
  max_runs_per_minute: number;
};

//: 下拉里表示"不限"的那一项。Radix 的 SelectItem 不收空串当值,拿一个撞不上的前缀顶上。
const ANY = "__any__";

function draftOf(trigger: WorkflowTrigger | null): Draft {
  return {
    name: trigger?.name ?? "",
    message_types: trigger?.message_types ?? ["text"],
    keywords: formatKeywords(trigger?.keywords ?? []),
    bot_id: trigger?.bot_id ?? "",
    chat_id: trigger?.chat_id ?? "",
    params: trigger?.params ?? {},
    reply_in_chat: trigger?.reply_in_chat ?? true,
    max_runs_per_minute: trigger?.max_runs_per_minute ?? 6,
  };
}

export function WorkflowTriggersDialog({
  workspaceId,
  workflow,
  open,
  onOpenChange,
  canEdit = true,
}: {
  workspaceId: string;
  workflow: { id: string; name: string; graph: unknown };
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** 只读成员看得到、看得见最近触发,但改不了(改要 `edit`,见 domain/triggers/use_cases)。 */
  canEdit?: boolean;
}) {
  const { t } = usePreferences();
  const qc = useQueryClient();
  const [editing, setEditing] = React.useState<WorkflowTrigger | "new" | null>(null);
  const [confirming, setConfirming] = React.useState<WorkflowTrigger | null>(null);

  const list = useQuery({
    queryKey: ["workflow-triggers", workspaceId, workflow.id],
    queryFn: () => listWorkflowTriggers(workspaceId, workflow.id),
    enabled: open,
  });
  const bots = useQuery({
    queryKey: ["feishu-bots", workspaceId],
    queryFn: () => api<BotLite[]>(`/api/feishu/bots?workspace_id=${encodeURIComponent(workspaceId)}`),
    enabled: open,
  });

  const invalidate = () => {
    void qc.invalidateQueries({ queryKey: ["workflow-triggers", workspaceId, workflow.id] });
  };
  const onFailed = (error: unknown) => toast.error(String((error as Error).message));
  const toggle = useMutation({
    mutationFn: (one: WorkflowTrigger) => updateWorkflowTrigger(one.id, { enabled: !one.enabled }),
    onSuccess: invalidate,
    onError: onFailed,
  });
  const remove = useMutation({
    mutationFn: (id: string) => deleteWorkflowTrigger(id),
    onSuccess: () => {
      setEditing(null);
      invalidate();
    },
    onError: onFailed,
  });

  const typeLabel = (kind: string) =>
    ({
      text: t("workflowTriggersTypeText"),
      image: t("workflowTriggersTypeImage"),
      file: t("workflowTriggersTypeFile"),
      media: t("workflowTriggersTypeMedia"),
    })[kind] ?? kind;

  return (
    <ModalShell
      open={open}
      onOpenChange={(next) => {
        if (!next) setEditing(null);
        onOpenChange(next);
      }}
      title={t("workflowTriggersTitle")}
      className="w-[560px] max-w-[92vw]"
      header={
        <div className="flex items-center justify-between gap-2">
          <p className="text-xs text-muted-foreground">
            {t("workflowTriggersDesc").replace("{name}", workflow.name)}
          </p>
          {editing === null && canEdit && (
            <Button size="sm" variant="outline" onClick={() => setEditing("new")}>
              <Plus size={13} /> {t("workflowTriggersAdd")}
            </Button>
          )}
        </div>
      }
      footer={
        <Button variant="outline" onClick={() => onOpenChange(false)}>
          {t("close")}
        </Button>
      }
    >
      {editing !== null ? (
        <TriggerForm
          key={editing === "new" ? "new" : editing.id}
          workspaceId={workspaceId}
          workflowId={workflow.id}
          startParams={startParamNamesOf(workflow.graph)}
          bots={bots.data ?? []}
          existing={editing === "new" ? null : editing}
          onDone={() => {
            setEditing(null);
            invalidate();
          }}
          onCancel={() => setEditing(null)}
        />
      ) : (
        <div className="grid gap-3">
          {list.isLoading && <Skeleton className="h-14 w-full" />}
          {!list.isLoading && (list.data ?? []).length === 0 && (
            <EmptyState
              size="section"
              icon={<Zap size={18} />}
              title={t("workflowTriggersEmpty")}
              body={t("workflowTriggersEmptyHint")}
            />
          )}
          {(list.data ?? []).map((one) => (
            <TriggerRow
              key={one.id}
              trigger={one}
              summary={triggerSummary(one, typeLabel, t("workflowTriggersBotAny"))}
              canEdit={canEdit}
              busy={toggle.isPending}
              onToggle={() => toggle.mutate(one)}
              onEdit={() => setEditing(one)}
              onDelete={() => setConfirming(one)}
            />
          ))}
        </div>
      )}
      <ConfirmDialog
        open={confirming !== null}
        title={t("workflowTriggersDelete")}
        body={t("workflowTriggersDeleteConfirm")}
        confirmLabel={t("delete")}
        pending={remove.isPending}
        onCancel={() => setConfirming(null)}
        onConfirm={() => {
          if (confirming) remove.mutate(confirming.id);
          setConfirming(null);
        }}
      />
    </ModalShell>
  );
}

function TriggerRow({
  trigger,
  summary,
  canEdit,
  busy,
  onToggle,
  onEdit,
  onDelete,
}: {
  trigger: WorkflowTrigger;
  summary: string;
  canEdit: boolean;
  /** 这颗开关自己的请求在跑;别的按钮不跟着一起灰 —— 那会变成"点了没反应"。 */
  busy: boolean;
  onToggle: () => void;
  onEdit: () => void;
  onDelete: () => void;
}) {
  const { t } = usePreferences();
  const [showEvents, setShowEvents] = React.useState(false);
  return (
    <div className="grid gap-2 rounded-lg border border-border p-3" data-workflow-trigger={trigger.id}>
      <div className="flex items-center justify-between gap-2">
        <span className="flex min-w-0 items-center gap-2">
          <Zap size={14} className="shrink-0 text-muted-foreground" />
          <Truncate className="text-sm font-medium">{trigger.name}</Truncate>
          {!trigger.enabled && <Badge variant="outline">{t("workflowTriggersOff")}</Badge>}
        </span>
        <span className="flex shrink-0 items-center gap-1">
          <Switch
            checked={trigger.enabled}
            disabled={busy || !canEdit}
            aria-label={trigger.name}
            onCheckedChange={onToggle}
          />
          {canEdit && (
            <Button size="sm" variant="ghost" onClick={onEdit}>
              {t("workflowTriggersEdit")}
            </Button>
          )}
          {canEdit && (
            <Button
              size="sm"
              variant="ghost"
              aria-label={`${t("workflowTriggersDelete")}: ${trigger.name}`}
              onClick={onDelete}
            >
              <Trash2 size={13} />
            </Button>
          )}
        </span>
      </div>
      <p className="text-xs text-muted-foreground">{summary}</p>
      <p className="text-xs text-muted-foreground">
        {trigger.last_fired_at
          ? t("workflowTriggersLastFired").replace("{time}", new Date(trigger.last_fired_at).toLocaleString())
          : t("workflowTriggersNeverFired")}
      </p>
      <div>
        <Button size="sm" variant="ghost" aria-expanded={showEvents} onClick={() => setShowEvents((one) => !one)}>
          <History size={13} /> {t("workflowTriggersRecent")}
        </Button>
      </div>
      {showEvents && <TriggerEvents triggerId={trigger.id} />}
    </div>
  );
}

/** 「最近触发」:哪条消息、怎么了、起了哪次运行。**这一屏就是"它在干活吗"的答案。** */
function TriggerEvents({ triggerId }: { triggerId: string }) {
  const { t } = usePreferences();
  const events = useQuery({
    queryKey: ["workflow-trigger-events", triggerId],
    queryFn: () => listWorkflowTriggerEvents(triggerId),
  });
  if (events.isLoading) return <Skeleton className="h-10 w-full" />;
  if ((events.data ?? []).length === 0) {
    return <p className="text-xs text-muted-foreground">{t("workflowTriggersRecentEmpty")}</p>;
  }
  const statusLabel: Record<string, string> = {
    started: t("workflowTriggersStatusStarted"),
    throttled: t("workflowTriggersStatusThrottled"),
    refused: t("workflowTriggersStatusRefused"),
    failed: t("workflowTriggersStatusFailed"),
    skipped: t("workflowTriggersStatusSkipped"),
  };
  const toneClass: Record<string, string> = {
    ok: "text-emerald-600",
    warn: "text-amber-600",
    bad: "text-destructive",
    muted: "text-muted-foreground",
  };
  return (
    <ul className="grid gap-1.5">
      {(events.data ?? []).map((one) => (
        <li key={one.id} className="grid gap-1" data-trigger-event={one.id}>
          <div className="flex items-center gap-2 text-xs">
            <span className={cn("shrink-0 font-medium", toneClass[eventTone(one.status)])}>
              {statusLabel[one.status] ?? one.status}
            </span>
            {/* 消息预览会很长:截断走 Truncate,真被截断了悬停看得到全文(棘轮 design/truncatedText)。 */}
            <Truncate className="min-w-0 flex-1 text-muted-foreground">
              {one.text_preview || t("workflowTriggersNoText")}
            </Truncate>
            {one.asset_ids.length > 0 && (
              <span className="shrink-0 text-muted-foreground">
                {t("workflowTriggersAssetsCount").replace("{n}", String(one.asset_ids.length))}
              </span>
            )}
            <span className="shrink-0 text-muted-foreground">{new Date(one.created_at).toLocaleString()}</span>
            {one.job_id && (
              <Button size="sm" variant="ghost" onClick={() => gotoJob(one.job_id as string)}>
                <Play size={13} /> {t("workflowTriggersOpenRun")}
              </Button>
            )}
          </div>
          {/* 没跑起来的原因走全应用那一份失败卡(棘轮 design/failureDisplays)。 */}
          {one.error && (
            <FailureCard size="inline" title={statusLabel[one.status] ?? one.status} summary={one.error} />
          )}
        </li>
      ))}
    </ul>
  );
}

function TriggerForm({
  workspaceId,
  workflowId,
  startParams,
  bots,
  existing,
  onDone,
  onCancel,
}: {
  workspaceId: string;
  workflowId: string;
  startParams: string[];
  bots: BotLite[];
  existing: WorkflowTrigger | null;
  onDone: () => void;
  onCancel: () => void;
}) {
  const { t } = usePreferences();
  const [draft, setDraft] = React.useState<Draft>(() => draftOf(existing));
  const patch = (changes: Partial<Draft>) => setDraft((one) => ({ ...one, ...changes }));

  const save = useMutation({
    mutationFn: async () => {
      const common = {
        workflow_id: workflowId,
        name: draft.name.trim(),
        bot_id: draft.bot_id,
        chat_id: draft.chat_id.trim(),
        message_types: draft.message_types,
        keywords: parseKeywords(draft.keywords),
        params: draft.params,
        reply_in_chat: draft.reply_in_chat,
        max_runs_per_minute: draft.max_runs_per_minute,
      };
      if (existing) return updateWorkflowTrigger(existing.id, common);
      return createWorkflowTrigger({ workspace_id: workspaceId, ...common });
    },
    onSuccess: () => {
      toast.success(t("workflowTriggersSaved"));
      onDone();
    },
    onError: (error: unknown) => toast.error(String((error as Error).message)),
  });

  const canSave = draft.name.trim().length > 0 && draft.message_types.length > 0 && !save.isPending;

  const toggleType = (kind: string) =>
    patch({
      message_types: draft.message_types.includes(kind)
        ? draft.message_types.filter((one) => one !== kind)
        : [...draft.message_types, kind],
    });

  const typeLabels: Record<string, string> = {
    text: t("workflowTriggersTypeText"),
    image: t("workflowTriggersTypeImage"),
    file: t("workflowTriggersTypeFile"),
    media: t("workflowTriggersTypeMedia"),
  };

  return (
    <div className="grid gap-3" data-workflow-trigger-form>
      <label className="grid gap-1 text-xs">
        <span className="font-medium">{t("workflowTriggersName")}</span>
        <Input
          value={draft.name}
          placeholder={t("workflowTriggersNamePlaceholder")}
          onChange={(event) => patch({ name: event.target.value })}
        />
      </label>

      <div className="grid gap-1 text-xs">
        <span className="font-medium">{t("workflowTriggersTypes")}</span>
        <div className="flex flex-wrap gap-1.5">
          {TRIGGER_TYPE_OPTIONS.map((kind) => (
            // 「开着」的样子由 Button 按 aria-pressed 画(见 control-size 的 PRESSED)——
            // 这里不自己切 variant、也不自己写颜色(棘轮 design/pressedState)。
            <Button
              key={kind}
              size="sm"
              variant="outline"
              aria-pressed={draft.message_types.includes(kind)}
              onClick={() => toggleType(kind)}
            >
              {typeLabels[kind]}
            </Button>
          ))}
        </div>
      </div>

      <label className="grid gap-1 text-xs">
        <span className="font-medium">{t("workflowTriggersKeywords")}</span>
        <Input
          value={draft.keywords}
          placeholder={t("workflowTriggersKeywordsPlaceholder")}
          onChange={(event) => patch({ keywords: event.target.value })}
        />
        <span className="text-muted-foreground">{t("workflowTriggersKeywordsHint")}</span>
      </label>

      <div className="grid grid-cols-2 gap-2 text-xs">
        <div className="grid gap-1">
          <span className="font-medium">{t("workflowTriggersBot")}</span>
          <Select value={draft.bot_id || ANY} onValueChange={(value) => patch({ bot_id: value === ANY ? "" : value })}>
            <SelectTrigger aria-label={t("workflowTriggersBot")}>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={ANY}>{t("workflowTriggersBotAny")}</SelectItem>
              {bots.map((bot) => (
                <SelectItem key={bot.id} value={bot.id}>
                  {bot.name}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        <label className="grid gap-1">
          <span className="font-medium">{t("workflowTriggersChat")}</span>
          <Input value={draft.chat_id} onChange={(event) => patch({ chat_id: event.target.value })} placeholder="oc_…" />
          <span className="text-muted-foreground">{t("workflowTriggersChatHint")}</span>
        </label>
      </div>

      <div className="grid gap-1 text-xs">
        <span className="font-medium">{t("workflowTriggersParams")}</span>
        <span className="text-muted-foreground">{t("workflowTriggersParamsHint")}</span>
        {startParams.length === 0 ? (
          <span className="text-muted-foreground">{t("workflowTriggersNoParams")}</span>
        ) : (
          <div className="grid gap-1.5">
            {startParams.map((param) => (
              <div key={param} className="flex items-center gap-2">
                <Truncate className="w-1/2 font-mono text-xs">{param}</Truncate>
                <Select
                  value={draft.params[param] ?? ANY}
                  onValueChange={(value) =>
                    patch({ params: withParamMapping(draft.params, param, value === ANY ? null : value) })
                  }
                >
                  <SelectTrigger aria-label={param}>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value={ANY}>{t("workflowTriggersParamUnmapped")}</SelectItem>
                    {TRIGGER_FIELD_OPTIONS.map((field) => (
                      <SelectItem key={field.value} value={field.value}>
                        {t(field.labelKey)}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            ))}
          </div>
        )}
      </div>

      <div className="flex items-center justify-between gap-2 text-xs">
        <label className="flex items-center gap-2">
          <Switch checked={draft.reply_in_chat} onCheckedChange={(checked) => patch({ reply_in_chat: checked })} />
          <span className="font-medium">{t("workflowTriggersReply")}</span>
        </label>
        <label className="flex items-center gap-2">
          <span className="font-medium">{t("workflowTriggersLimit")}</span>
          <Input
            className="w-16"
            type="number"
            min={1}
            max={60}
            value={draft.max_runs_per_minute}
            onChange={(event) => patch({ max_runs_per_minute: Number(event.target.value) || 1 })}
          />
        </label>
      </div>
      <p className="text-xs text-muted-foreground">{t("workflowTriggersReplyHint")}</p>

      <div className="flex justify-end gap-2">
        <Button variant="outline" onClick={onCancel}>
          {t("cancel")}
        </Button>
        <Button disabled={!canSave} loading={save.isPending} onClick={() => save.mutate()}>
          {t("save")}
        </Button>
      </div>
    </div>
  );
}
