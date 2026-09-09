/** @vitest-environment jsdom */
import React from "react";
import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("@/app/preferences", () => ({
  useI18n: () => (key: string) => ({ markers: "标记", markerEmpty: "这张画布上还没有标记" })[key] ?? key,
  usePreferences: () => ({ locale: "zh-CN" }),
}));

import { MarkerListButton } from "./MarkerListButton";

afterEach(cleanup);

describe("标记清单", () => {
  /**
   * 清单回答的是「有哪些、在哪儿」。
   *
   * 它底下曾经挂过一个「添加标记」—— 和左边那枚进入标记模式的按钮是同一件事,而且得先展开
   * 清单才看得见:更长的一条路,做的是旁边那枚按钮已经在做的事。空清单时更荒唐:一句「还没有
   * 标记」底下杵着一个加号,读起来像是这里才是加标记的地方。
   */
  it("不提供添加入口 —— 那是工具条的事", async () => {
    render(<MarkerListButton markers={[]} onJump={vi.fn()} />);
    await userEvent.click(screen.getByRole("button", { name: "标记" }));
    expect(await screen.findByText("这张画布上还没有标记")).toBeInTheDocument();
    // 展开后除了触发器本身,不该再多出任何按钮。
    expect(screen.getAllByRole("button")).toHaveLength(1);
  });

  it("点一条就跳过去", async () => {
    const onJump = vi.fn();
    const marker = { id: "m1", name: "开场", x: 0, y: 0, shortcut: "Mod+1" };
    render(<MarkerListButton markers={[marker]} onJump={onJump} />);
    await userEvent.click(screen.getByRole("button", { name: "标记" }));
    await userEvent.click(await screen.findByText("开场"));
    expect(onJump).toHaveBeenCalledWith(marker);
  });
});
