/**
 * 对话里「这是一次选择、选了哪一项」的那条记录 —— **它属于用户那条消息**。
 *
 * 选择卡答完就消失了,所以得在对话里留一条痕迹 —— 这一点原本就是对的。错的是留下来的形状和
 * 位置:后端把答案拼成一句「我选好了:· 问题:答案」当**用户消息**发回去,于是一次选择在对话里
 * 退化成一段你自己说的话,问题和选项的结构全丢了,看起来还像是你手打的。正文照留(模型读的是
 * 它),结构另存一份(`payload.answers`),这里负责把结构画回来:问的是什么、选的是哪一项。
 *
 * **谁做的,决定它画在哪。** 选择是用户做的事,记录就该长在用户那条消息里(`AnsweredChoiceCard`)。
 * 助手那一侧只有它自己那一步:这次 `ask_user` 有没有拿回答案 —— 一行状态(`AnsweredChoiceStatus`)。
 * 此前助手的结果卡复用了这张记录卡,于是用户的选择被画进助手的消息、还带着「你在选择卡上选了…」
 * 的第一人称口吻,助手替用户转述了他的选择。维护者截图里那一行就是这个(原话:「这是不对的」)。
 *
 * 两处都改名目性的标签,不写句子:「已选」「已跳过」。谁点的不写在标签里 —— 位置已经说清楚了。
 */

import React from "react";
import { CircleCheck, SkipForward } from "lucide-react";

import { useI18n } from "@/app/preferences";

export interface AnsweredChoice {
  /** 用户按了「跳过」。那时没有选项可画,只说明模型收到的是"他不答"。 */
  dismissed?: boolean;
  picked?: { question: string; choices: string[] }[];
}

/** 用户那条消息里的记录:问的是什么、选的是哪一项。 */
export function AnsweredChoiceCard({ answers }: { answers: AnsweredChoice }) {
  const t = useI18n();
  if (answers.dismissed)
    return (
      <div
        data-answer-record=""
        className="flex items-center gap-1.5 rounded-lg border border-border bg-panel-subtle px-2.5 py-2 text-ui-sm text-muted-foreground"
      >
        <SkipForward size={13} className="shrink-0" />
        <span>{t("agentChoiceDismissed")}</span>
      </div>
    );
  const picked = answers.picked ?? [];
  if (!picked.length) return null;
  return (
    <div data-answer-record="" className="grid gap-1.5 rounded-lg border border-border bg-panel-subtle px-2.5 py-2">
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

/**
 * 助手那一侧的状态:这一步拿回了答案。
 *
 * 不是一条记录 —— 记录在用户那条消息里。所以这里只写「拿到了什么」:一个名目性的标签和几个
 * 值,用次要色,不画问题、不摆成正文字号、也不用第一人称。折叠时它跟着工具明细一起收起。
 */
export function AnsweredChoiceStatus({ answers }: { answers: AnsweredChoice }) {
  const t = useI18n();
  if (answers.dismissed)
    return (
      <div data-answer-status="" className="flex items-center gap-1.5 text-ui-xs text-muted-foreground">
        <SkipForward size={12} className="shrink-0" aria-hidden />
        <span>{t("agentChoiceDismissed")}</span>
      </div>
    );
  const values = (answers.picked ?? []).flatMap((one) => one.choices).filter(Boolean);
  if (!values.length) return null;
  return (
    <div data-answer-status="" className="flex flex-wrap items-center gap-1.5 text-ui-xs text-muted-foreground">
      <CircleCheck size={12} className="shrink-0" aria-hidden />
      <span>{t("agentChoiceAnswered")}</span>
      {values.map((value, index) => (
        <span key={`${value}-${index}`} className="rounded-sm border border-border px-1 py-px [overflow-wrap:anywhere]">
          {value}
        </span>
      ))}
    </div>
  );
}
