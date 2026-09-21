/** @vitest-environment jsdom */

/**
 * 失败的那一轮,**已经做过的事照样要看得见**。
 *
 * 用户报的是:一次跑了 3 分 19 秒、9136 token 的对话,最后一步 `Connection error.`,整轮过程
 * 全没了,只剩一句「智能体执行失败」。此前这里是二选一 —— 只要消息带 `error` 就只画错误卡,
 * `payload.timeline` 有没有都不看。
 *
 * 还有一条:选择卡答完就消失,后端于是把答案拼成一句「我选好了:· 问题:答案」当**用户消息**
 * 发回去。留痕迹是对的,但一次选择在对话里退化成了一段你自己说的话,问题和选项的结构全丢了。
 */

import React from "react";
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

vi.mock("@/app/preferences", () => ({
  useI18n: () => (key: string) =>
    ({
      agentFailedTitle: "智能体执行失败",
      chatErrorDetail: "错误详情",
      agentChoiceAnswered: "你在选择卡上选了",
      agentChoiceDismissed: "你跳过了这几个问题,让它自己判断",
    })[key] ?? key,
  usePreferences: () => ({ locale: "zh" }),
}));

import { AgentErrorCard, AgentTurnContent } from "./ToolCalls";
import { AnsweredChoiceCard } from "./AnsweredChoice";
import { ToolResultCard } from "./toolResultShapes";

describe("失败的一轮", () => {
  it("过程和失败原因同时在，而不是二选一", () => {
    // 气泡现在的写法:先 AgentTurnContent，再在下面挂 AgentErrorCard。
    render(
      <>
        <AgentTurnContent timeline={[{ type: "text", text: "我先看了八个房间的白模。" }]} />
        <AgentErrorCard content="智能体执行失败，请稍后重试。" error="Connection error." />
      </>,
    );
    expect(screen.getByText("我先看了八个房间的白模。")).toBeTruthy();
    expect(screen.getByText("智能体执行失败，请稍后重试。")).toBeTruthy();
  });

  it("没有过程时只剩错误卡，不多画一个空块", () => {
    const { container } = render(<AgentTurnContent timeline={[]} />);
    expect(container.textContent).toBe("");
  });
});

describe("答完的选择卡", () => {
  it("画的是「问了什么、选了哪一项」，不是一段自述", () => {
    render(
      <AnsweredChoiceCard
        answers={{
          picked: [
            { question: "接下来想先做哪件事？", choices: ["修一下道具/人物细节"] },
            { question: "要统一朝向吗？", choices: ["统一成正面朝窗"] },
          ],
        }}
      />,
    );
    expect(screen.getByText("你在选择卡上选了")).toBeTruthy();
    expect(screen.getByText("接下来想先做哪件事？")).toBeTruthy();
    expect(screen.getByText("修一下道具/人物细节")).toBeTruthy();
    expect(screen.getByText("统一成正面朝窗")).toBeTruthy();
    // 「我选好了:」那句是发给模型的正文，不该出现在界面上。
    expect(screen.queryByText(/我选好了/)).toBeNull();
  });

  it("跳过了也说清楚 —— 模型收到的是「他不答」", () => {
    render(<AnsweredChoiceCard answers={{ dismissed: true }} />);
    expect(screen.getByText("你跳过了这几个问题,让它自己判断")).toBeTruthy();
  });
});

/**
 * `ask_user` 这一步的结果卡要写着**用户选了什么**。
 *
 * 此前它掉进通用的键值摘要:卡片上是「状态 answered / answers 2 个字段」—— 而这次调用的
 * 全部意义就是那个选择。要看它得展开原始 JSON,翻过一整段选项定义才找得到。
 */
describe("ask_user 的结果卡", () => {
  it("画出问题和选中的那一项,而不是「answers 2 个字段」", () => {
    render(
      <ToolResultCard
        value={{
          status: "answered",
          answers: { "这次要做成什么规格？": ["16:9 横屏"], "从哪儿开始？": "先搭主体" },
        }}
      />,
    );
    expect(screen.getByText("这次要做成什么规格？")).toBeTruthy();
    expect(screen.getByText("16:9 横屏")).toBeTruthy();
    // 单选也画得出来(后端存的是列表,但别处可能给单值)。
    expect(screen.getByText("先搭主体")).toBeTruthy();
    expect(screen.queryByText(/个字段/)).toBeNull();
  });

  it("跳过了也说清楚", () => {
    render(<ToolResultCard value={{ status: "dismissed", skipped: true }} />);
    expect(screen.getByText("你跳过了这几个问题,让它自己判断")).toBeTruthy();
  });
});
