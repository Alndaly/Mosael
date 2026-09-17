/** @vitest-environment jsdom */
/**
 * 输入框上方那一条条还没发出去的消息。
 *
 * 这一条此前在对话页和画布助手里各抄了一遍,两处都写死 `w-full max-w-[780px]` —— 而两边的
 * 输入框各有各的留边(对话页 `calc(100%-32px)`、画布助手 `mx-2`)。窗口一窄(分屏、侧栏),
 * 输入框缩进去了,这一条还顶着两侧边缘,同一件事的两个盒子对不齐。
 *
 * 判据是**宽度由调用方给、并且真的落到那一条上**:jsdom 里量不到版面,但"这一条有没有
 * 拿到那一列的宽度"是能钉的 —— 而调用方两边都把同一个 COMPOSER_COLUMN 常量给了它和输入框。
 */
import { fireEvent, render, screen } from "@testing-library/react";
import React from "react";
import { expect, it, vi } from "vitest";

vi.mock("@/app/preferences", () => ({ useI18n: () => (k: string) => k, usePreferences: () => ({ locale: "zh-CN" }) }));

import { QueuedMessages } from "./QueuedMessages";

const MESSAGES = [{ id: "q1", content: "我想要英文" }];

it("这一条的宽度就是调用方给的那一列 —— 不自带一个和输入框对不上的写死值", () => {
  const { container } = render(
    <QueuedMessages messages={MESSAGES} className="mx-2" onSteer={() => {}} onCancel={() => {}} />,
  );
  const row = container.firstElementChild as HTMLElement;
  expect(row.className).toContain("mx-2");
  //: 旧版那个写死的宽度不能再混在里面,否则两个来源打架,窄窗口下还是对不齐。
  expect(row.className).not.toContain("max-w-[780px]");
  expect(row.className).not.toContain("w-full");
});

it("插进这一轮和撤回各自点到自己那一条", () => {
  const steer = vi.fn();
  const cancel = vi.fn();
  render(
    <QueuedMessages
      messages={[...MESSAGES, { id: "q2", content: "再补一句" }]}
      onSteer={steer}
      onCancel={cancel}
    />,
  );
  fireEvent.click(screen.getAllByText("chatSteerAction")[1]);
  expect(steer).toHaveBeenCalledWith("q2");
  fireEvent.click(screen.getAllByLabelText("chatQueuedCancel")[0]);
  expect(cancel).toHaveBeenCalledWith("q1");
});
