import React from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Check, HelpCircle } from "lucide-react";

import { api } from "@/api/client";
import type { components } from "@/api/generated/schema";
import { useI18n } from "@/app/preferences";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";

type Question = components["schemas"]["AgentQuestionOut"];

/**
 * 聊天流里的**选择卡**:智能体在岔路口把选项摊开,用户点一下。
 *
 * 和确认卡(InlineConfirmations)长得像,但**是两件事**:确认卡问「这件事能不能做」,
 * 可以被「本会话始终允许」自动批准;这里问「你要哪一个」—— 自动回答等于让模型自己编一个,
 * 所以后端那一侧就没有任何自动通路(见 domain/agent/questions)。
 *
 * 「其它」是自由文本:模型给的选项常常不全,而逼人从三个都不对的里面挑一个,比不问还糟。
 */
export function InlineQuestions({ sessionId }: { sessionId: string }) {
  const qc = useQueryClient();
  const pending = useQuery({
    queryKey: ["agent-questions", sessionId],
    queryFn: () => api<Question[]>(`/api/agent/questions?session_id=${sessionId}`),
    // 模型问完之后卡片要尽快出现 —— 它此刻正阻塞着等答案。
    refetchInterval: 2000,
  });

  const rows = pending.data ?? [];
  if (rows.length === 0) return null;
  return (
    <div className="grid gap-2">
      {rows.map((row) => (
        <QuestionCard
          key={row.id}
          row={row}
          onDone={() => void qc.invalidateQueries({ queryKey: ["agent-questions", sessionId] })}
        />
      ))}
    </div>
  );
}

function QuestionCard({ row, onDone }: { row: Question; onDone: () => void }) {
  const t = useI18n();
  const items = row.questions ?? [];
  // 每个问题选中的 label 集合。多选是集合,单选也是集合(长度 1)—— 两种形状分开写的话,
  // 提交那一步要判两遍。
  const [picked, setPicked] = React.useState<Record<string, string[]>>({});
  const [other, setOther] = React.useState<Record<string, string>>({});

  const answer = useMutation({
    mutationFn: (answers: Record<string, string[]>) =>
      api(`/api/agent/questions/${row.id}/answer`, { method: "POST", body: JSON.stringify({ answers }) }),
    onSuccess: onDone,
  });
  const skip = useMutation({
    mutationFn: () => api(`/api/agent/questions/${row.id}/dismiss`, { method: "POST" }),
    onSuccess: onDone,
  });

  const answersFor = (): Record<string, string[]> =>
    Object.fromEntries(
      items.map((item) => {
        const free = (other[item.question] ?? "").trim();
        const chosen = picked[item.question] ?? [];
        return [item.question, free ? [...chosen, free] : chosen];
      }),
    );
  // 每个问题都得有答案才能提交 —— 少答一个,模型收到的是一份它没法用的回复。
  const complete = items.every((item) => (answersFor()[item.question] ?? []).length > 0);

  const toggle = (item: (typeof items)[number], label: string) =>
    setPicked((current) => {
      const chosen = current[item.question] ?? [];
      if (item.multi_select) {
        return {
          ...current,
          [item.question]: chosen.includes(label) ? chosen.filter((one) => one !== label) : [...chosen, label],
        };
      }
      return { ...current, [item.question]: chosen[0] === label ? [] : [label] };
    });

  return (
    <div className="mx-auto grid w-full max-w-[780px] gap-3 rounded-lg border border-border bg-panel-subtle p-3">
      {items.map((item) => {
        const chosen = picked[item.question] ?? [];
        return (
          <div key={item.question} className="grid gap-2">
            <div className="flex flex-wrap items-center gap-1.5">
              <HelpCircle size={13} className="shrink-0 text-muted-foreground" />
              {item.header && (
                <span className="shrink-0 rounded-sm bg-secondary px-1.5 py-0.5 text-ui-2xs font-semibold text-muted-foreground">
                  {item.header}
                </span>
              )}
              <span className="text-ui-sm font-semibold text-foreground">{item.question}</span>
              {item.multi_select && <span className="text-ui-2xs text-muted-foreground">{t("askMultiHint")}</span>}
            </div>
            <div className="grid gap-1.5">
              {(item.options ?? []).map((option) => (
                <button
                  key={option.label}
                  type="button"
                  className={cn(
                    "grid cursor-pointer gap-0.5 rounded-md border bg-panel px-2.5 py-2 text-left transition-colors duration-100",
                    chosen.includes(option.label)
                      ? "border-primary bg-accent"
                      : "border-border hover:border-border-strong",
                  )}
                  onClick={() => toggle(item, option.label)}
                >
                  <span className="flex items-center gap-1.5 text-ui-sm font-semibold text-foreground">
                    {chosen.includes(option.label) && <Check size={12} className="shrink-0 text-primary" />}
                    {option.label}
                  </span>
                  {option.description && (
                    <span className="text-ui-xs leading-[1.5] text-muted-foreground">{option.description}</span>
                  )}
                </button>
              ))}
              {/* 模型给的选项常常不全。逼人从三个都不对的里面挑一个,比不问还糟。 */}
              <Input
                className="h-8 rounded-md border-border bg-panel px-2.5 text-ui-sm"
                placeholder={t("askOtherPlaceholder")}
                value={other[item.question] ?? ""}
                onChange={(event) => setOther((current) => ({ ...current, [item.question]: event.target.value }))}
              />
            </div>
          </div>
        );
      })}
      <div className="flex items-center justify-end gap-1.5">
        <Button variant="ghost" size="sm" loading={skip.isPending} onClick={() => skip.mutate()}>
          {t("askSkip")}
        </Button>
        <Button size="sm" disabled={!complete} loading={answer.isPending} onClick={() => answer.mutate(answersFor())}>
          {t("askSubmit")}
        </Button>
      </div>
    </div>
  );
}
