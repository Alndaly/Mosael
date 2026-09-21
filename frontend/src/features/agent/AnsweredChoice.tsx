/**
 * 对话里「这是一次选择,你选了哪一项」的那条记录。
 *
 * 选择卡答完就消失了,所以得在对话里留一条痕迹 —— 这一点原本就是对的。错的是留下来的形状:
 * 后端把答案拼成一句「我选好了:· 问题:答案」当**用户消息**发回去,于是一次选择在对话里
 * 退化成一段你自己说的话,问题和选项的结构全丢了,看起来还像是你手打的。
 *
 * 正文照留(模型读的是它),这里只负责把**结构**画回来:问的是什么、你选的是哪一项。
 */

import React from "react";
import { CircleCheck, SkipForward } from "lucide-react";

import { useI18n } from "@/app/preferences";

export interface AnsweredChoice {
  /** 用户按了「跳过」。那时没有选项可画,只说明模型收到的是"他不答"。 */
  dismissed?: boolean;
  picked?: { question: string; choices: string[] }[];
}

export function AnsweredChoiceCard({ answers }: { answers: AnsweredChoice }) {
  const t = useI18n();
  if (answers.dismissed)
    return (
      <div className="flex items-center gap-1.5 rounded-lg border border-border bg-panel-subtle px-2.5 py-2 text-ui-sm text-muted-foreground">
        <SkipForward size={13} className="shrink-0" />
        <span>{t("agentChoiceDismissed")}</span>
      </div>
    );
  const picked = answers.picked ?? [];
  if (!picked.length) return null;
  return (
    <div className="grid gap-1.5 rounded-lg border border-border bg-panel-subtle px-2.5 py-2">
      <span className="text-ui-xs font-medium text-muted-foreground">{t("agentChoiceAnswered")}</span>
      {picked.map((one, index) => (
        <div key={`${one.question}-${index}`} className="grid gap-1">
          {/* 问题是模型问的,所以是次要色;选中项才是这条记录的内容。 */}
          <span className="text-ui-sm text-muted-foreground [overflow-wrap:anywhere]">{one.question}</span>
          <div className="flex flex-wrap gap-1">
            {one.choices.map((choice) => (
              <span
                key={choice}
                className="inline-flex max-w-full items-center gap-1 rounded-md border border-[color-mix(in_srgb,var(--primary)_45%,transparent)] bg-[color-mix(in_srgb,var(--primary)_10%,transparent)] px-1.5 py-px text-ui-xs text-primary"
              >
                <CircleCheck size={11} className="shrink-0" />
                <span className="[overflow-wrap:anywhere]">{choice}</span>
              </span>
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}
