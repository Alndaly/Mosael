/** @vitest-environment jsdom */
import { fireEvent, render, screen } from "@testing-library/react";
import React from "react";
import { describe, expect, it, vi } from "vitest";

import type { Confirmation } from "@/api/client";

vi.mock("@/app/preferences", () => ({
  useI18n: () => (key: string) => key,
  usePreferences: () => ({ locale: "zh-CN" }),
}));

import { ConfirmationCard, PREVIEW_LINES } from "@/features/agent/ConfirmationCard";

/** 截图里那张:运行 Manim 的「自定义动画」,一段二十行的 Python。 */
const MANIM = Array.from({ length: 20 }, (_, index) => (index === 0 ? "import numpy as np" : `line_${index} = ${index}`)).join("\n");

function card(overrides: Partial<Confirmation> = {}): Confirmation {
  return {
    id: "c1",
    workspace_id: "w1",
    session_id: "s1",
    tool: "plugin__manim__custom_animation",
    allow_tool: "plugin__manim__custom_animation",
    permission: "external",
    summary: "运行插件工具「Manim 自定义动画」(连接「Manim 教学动画」),参数:`code=import numpy as np…`  ⚠️ 会在你的电脑上运行代码",
    headline: "运行插件工具「Manim 自定义动画」(连接「Manim 教学动画」)",
    warning: "会在你的电脑上运行代码",
    always_asks: false,
    choices: {},
    summary_key: "confirm_runPluginTool",
    summary_params: {},
    payload: {
      arguments: { code: MANIM, fps: 30, filename: "scene.mp4" },
      instance_id: "i1",
      tool_name: "custom_animation",
      tool_label: "Manim 自定义动画",
      connection: "Manim 教学动画",
      effects: "local-code",
    },
    status: "pending",
    result: {},
    error: null, error_summary: null, error_detail: null, error_hint: null,
    requested_by: "agent",
    decision_mode: "manual",
    decided_by: null,
    created_at: "2026-10-01T00:00:00Z",
    resolved_at: null,
    ...overrides,
  };
}

function renderCard(item: Confirmation, extra: Partial<React.ComponentProps<typeof ConfirmationCard>> = {}) {
  return render(
    <ConfirmationCard item={item} eyebrow="智能体请求" actions={<button type="button">允许一次</button>} {...extra} />,
  );
}

describe("确认卡的层级", () => {
  it("标题用去掉后果与参数摘要的 headline,后果单独成一条提示", () => {
    const { container } = renderCard(card());
    const title = container.querySelector("article > p")!;
    expect(title.textContent).toBe("运行插件工具「Manim 自定义动画」(连接「Manim 教学动画」)");
    const notice = screen.getByRole("note");
    expect(notice.textContent).toBe("会在你的电脑上运行代码");
    //: 头部那一行只有请求方和徽标 —— 标题、警告不再和它们挤在一行。
    expect(container.querySelector("header")!.textContent).toBe("智能体请求permExternal");
  });

  it("老卡没有 headline 就用 summary", () => {
    const { container } = renderCard(card({ headline: "", warning: "", summary: "老卡的原话" }));
    expect(container.querySelector("article > p")!.textContent).toBe("老卡的原话");
    expect(screen.queryByRole("note")).toBeNull();
  });

  it("窄对话栏里不横向溢出:网格列可压缩、标题可断行、请求方一行截断", () => {
    const { container } = renderCard(card());
    const article = container.querySelector("article")!;
    expect(article.className).toContain("min-w-0");
    expect(article.className).toContain("grid-cols-[minmax(0,1fr)]");
    const title = container.querySelector("article > p")!;
    expect(title.className).toContain("[overflow-wrap:anywhere]");
    expect(title.className).not.toContain("whitespace-nowrap");
    expect(container.querySelector("header > span")!.className).toContain("truncate");
    //: 参数表的值一列可以断行,键那一列最多占四成。
    expect(container.querySelector("dl")!.className).toContain("grid-cols-[fit-content(40%)_minmax(0,1fr)]");
    expect(container.querySelector("dd")!.className).toContain("[overflow-wrap:anywhere]");
  });
});

describe("参数", () => {
  it("短参数是键值两列;工具名、连接、后果、实例 id 已在卡上别处,不重复列", () => {
    const { container } = renderCard(card());
    const keys = [...container.querySelectorAll("dt")].map((node) => node.textContent);
    expect(keys).toEqual(["fps", "filename"]);
    expect([...container.querySelectorAll("dd")].map((node) => node.textContent)).toEqual(["30", "scene.mp4"]);
  });

  it("代码参数还原真实换行,标着语言和总行数,默认只露前几行", () => {
    const { container } = renderCard(card());
    const block = container.querySelector("[data-field='code']")!;
    expect(block.textContent).toContain("python · confirmLineCount");
    const code = block.querySelector("pre")!;
    //: 真的换行,不是 JSON 转义出来的两个字符 `\` `n`。
    expect(code.textContent).toContain("import numpy as np\nline_1 = 1");
    expect(code.textContent).not.toContain("\\n");
    expect(code.textContent!.split("\n")).toHaveLength(PREVIEW_LINES);
    expect(code.textContent).not.toContain("line_19");
  });

  it("点开看全部,再点收起", () => {
    const { container } = renderCard(card());
    const toggle = screen.getByRole("button", { name: "confirmShowAll" });
    expect(toggle.getAttribute("aria-expanded")).toBe("false");
    fireEvent.click(toggle);
    const code = container.querySelector("[data-field='code'] pre")!;
    expect(code.textContent!.split("\n")).toHaveLength(20);
    expect(code.textContent).toContain("line_19 = 19");
    expect(screen.getByRole("button", { name: "confirmCollapse" }).getAttribute("aria-expanded")).toBe("true");
  });

  it("短的多行文本不折叠,也没有展开按钮", () => {
    renderCard(card({ payload: { prompt: "第一行\n第二行" } }));
    expect(screen.queryByRole("button", { name: "confirmShowAll" })).toBeNull();
  });

  it("原始数据还在,一字不少", () => {
    const { container } = renderCard(card());
    const raw = container.querySelector("details pre")!;
    expect(JSON.parse(raw.textContent!)).toEqual(card().payload);
  });
});

describe("终态", () => {
  it.each([
    ["executed", "confirmStatusExecuted"],
    ["rejected", "confirmStatusRejected"],
    ["approved", "confirmStatusApproved"],
  ])("%s:不再有按钮、后果提示和参数,只剩一行状态", (status, label) => {
    const { container } = renderCard(card({ status }));
    expect(screen.queryByText("允许一次")).toBeNull();
    expect(screen.queryByRole("note")).toBeNull();
    expect(container.querySelector("dl")).toBeNull();
    expect(screen.getByRole("status").textContent).toContain(label);
  });

  it("执行失败把原因写在状态行里,可以移走", () => {
    const dismiss = vi.fn();
    renderCard(card({ status: "failed", error: "manim 没装" }), { onDismiss: dismiss });
    const line = screen.getByRole("status");
    expect(line.textContent).toContain("confirmStatusFailed");
    expect(line.textContent).toContain("manim 没装");
    fireEvent.click(screen.getByRole("button", { name: "confirmDismiss" }));
    expect(dismiss).toHaveBeenCalledOnce();
  });

  it("长原因先折起来,点开读到的是整句 —— 后端不再截成半句,排版归这里", () => {
    const reason = Array.from({ length: 30 }, (_, index) => `节点 n${index} 缺少必填项「提示词」`).join(";") + "。最后一句才说怎么修。";
    renderCard(card({ status: "failed", error: reason }));
    const line = screen.getByRole("status");
    expect(line.textContent).not.toContain("最后一句才说怎么修");
    const toggle = screen.getByRole("button", { name: "confirmErrorShowAll" });
    expect(toggle.getAttribute("aria-expanded")).toBe("false");
    fireEvent.click(toggle);
    expect(line.textContent).toContain(reason);
    fireEvent.click(screen.getByRole("button", { name: "confirmCollapse" }));
    expect(line.textContent).not.toContain("最后一句才说怎么修");
  });

  it("短原因不折,也没有展开按钮", () => {
    renderCard(card({ status: "failed", error: "manim 没装" }));
    expect(screen.queryByRole("button", { name: "confirmErrorShowAll" })).toBeNull();
  });
});

describe("风险徽标按档位取色", () => {
  it.each([
    ["external", "danger"],
    ["destroy", "danger"],
    ["ai-cost", "caution"],
    ["render-cost", "caution"],
    ["edit", "neutral"],
    //: 不认识的档按最重的算 —— 授权界面上认不出来不等于没事。
    ["something-new", "danger"],
  ])("%s → %s", (permission, tone) => {
    const { container } = renderCard(card({ permission }));
    const badge = container.querySelector("[data-tone]")!;
    expect(badge.getAttribute("data-tone")).toBe(tone);
    expect(badge.className).toContain("shrink-0");
    expect(badge.className).toContain("whitespace-nowrap");
  });

  it("后果提示和徽标同一个色调:花钱的是提醒色,不是报错色", () => {
    renderCard(card({ permission: "ai-cost", warning: "会产生费用或占用付费算力" }));
    expect(screen.getByRole("note").className).toContain("var(--warning)");
  });
});
