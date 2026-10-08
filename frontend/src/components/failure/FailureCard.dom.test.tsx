/** @vitest-environment jsdom */
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("@/app/preferences", () => ({
  useI18n: () => (key: string) => key,
  usePreferences: () => ({ locale: "zh-CN" }),
}));

import { FailureCard, failureFields, rawFailureFields } from "@/components/failure/FailureCard";

afterEach(cleanup);

const FIX = { cause: "那台 ComfyUI 太旧", steps: [{ text: "升级:", command: 'pip install -U "comfy-kitchen>=0.2.37"' }, { text: "重启 ComfyUI。" }] };

describe("全应用那一份失败展示", () => {
  it("完整档:卡头状态(只有它带状态色)、那一句、原因和怎么修、动作行右边是详情开关和复制", () => {
    render(<FailureCard title="运行失败" meta={<span>工作流 · 2.0s</span>} summary="ComfyUI 执行到「KSampler」这一步出错"
                        detail="KSampler: hostbuf_file_reader_read failed" fix={FIX} copyText="原文整句"
                        actions={<button type="button">重试</button>} />);
    const card = screen.getByRole("group", { name: "运行失败" });
    expect(card.className).not.toMatch(/destructive/);
    expect(card.querySelector("[data-failure-meta]")?.textContent).toBe("工作流 · 2.0s");
    expect(card.querySelector("[data-failure-summary]")?.className).toMatch(/text-foreground/);
    expect([...card.querySelectorAll("[data-failure-fix] dt")].map((one) => one.textContent)).toEqual(["failureCause", "failureFix"]);
    expect(card.querySelectorAll("[data-failure-steps] > li")).toHaveLength(2);
    expect(card.querySelector("[data-failure-command] code")?.className, "等宽字体不把 >= 画成连字").toMatch(/\[font-variant-ligatures:none\]/);
    const actions = card.querySelector("[data-failure-actions]")!;
    expect(actions.firstElementChild?.textContent, "该点的在左").toBe("重试");
    const toggle = actions.querySelector<HTMLButtonElement>("[data-failure-detail-toggle]")!;
    expect(toggle.getAttribute("aria-expanded")).toBe("false");
    expect(card.querySelector<HTMLElement>("[data-failure-detail]")!.hidden).toBe(true);
    fireEvent.click(toggle);
    expect(card.querySelector<HTMLElement>("[data-failure-detail]")!.hidden).toBe(false);
    expect(actions.querySelectorAll("[data-failure-copy]")).toHaveLength(1);
  });

  it("没有 hint 的只有一句话加详情,不硬凑「原因 / 怎么修」;没有详情就不摆开关", () => {
    render(<FailureCard title="发布失败" summary="等「发布」按钮超时" copyText="Timeout 30000ms exceeded." />);
    const card = screen.getByRole("group", { name: "发布失败" });
    expect(card.querySelector("[data-failure-fix]")).toBeNull();
    expect(card.querySelector("[data-failure-detail-toggle]")).toBeNull();
    expect(card.querySelector("[data-failure-head] [data-failure-copy]"), "动作那一行只剩复制时不单占一行,放进卡头").not.toBeNull();
    expect(card.querySelector("[data-failure-actions]")).toBeNull();
  });

  it("「已停止」同一个壳:灰色的图标和标题,不是失败的红", () => {
    render(<FailureCard status="stopped" title="已停止" summary="在生成完之前停下了。" />);
    const card = screen.getByRole("group", { name: "已停止" });
    expect(card.getAttribute("data-failure-status")).toBe("stopped");
    expect(document.getElementById(card.getAttribute("aria-labelledby")!)!.className).toMatch(/text-muted-foreground/);
    expect(card.querySelector("[data-failure-actions]"), "没有原文、没有动作:不摆空的一行").toBeNull();
  });

  it.each(["compact", "inline"] as const)("%s 档:那一句在外面,原因、怎么修、原文、复制在点开的「详情」浮层里(原文直接展开)", async (size) => {
    render(<FailureCard size={size} title="生成失败" summary="ComfyUI 执行到「KSampler」这一步出错" detail="KSampler: boom" fix={FIX} copyText="整句" />);
    const card = screen.getByRole("group", { name: "生成失败" });
    expect(card.getAttribute("data-failure-size")).toBe(size);
    expect(card.querySelector("[data-failure-fix]"), "格子里不撑大").toBeNull();
    const more = card.querySelector<HTMLButtonElement>("[data-failure-more]")!;
    expect(more.className, "在画布的格子里点它不拖动画布").toMatch(/\bnodrag\b/);
    fireEvent.click(more);
    const panel = (await screen.findByText("那台 ComfyUI 太旧")).closest("[data-failure-popover]")!;
    expect(panel.querySelector<HTMLElement>("[data-failure-detail]")!.hidden).toBe(false);
    expect(panel.querySelector("[data-failure-command]")).not.toBeNull();
    expect(panel.querySelector("[data-failure-copy]")).not.toBeNull();
  });

  it("紧凑档、一行档只有那一句时不摆「详情」", () => {
    render(<FailureCard size="inline" title="失败" summary="磁盘满了" />);
    expect(document.querySelector("[data-failure-more]")).toBeNull();
  });
});

describe("从数据读那几样", () => {
  it("failureFields:后端摘好的那一句优先,没有就用原文;复制的是整句原文", () => {
    expect(failureFields({ error: "整句", error_summary: "那一句", error_detail: "原文", error_hint: FIX }, "兜底"))
      .toEqual({ summary: "那一句", detail: "原文", fix: FIX, copyText: "整句" });
    expect(failureFields({ error: " 只有原文 " }, "兜底")).toEqual({ summary: "只有原文", detail: null, fix: null, copyText: "只有原文" });
    expect(failureFields({}, "兜底").summary).toBe("兜底");
  });

  it("rawFailureFields:第一行当那一句(长了截到一句的长度),原文比它多时进详情", () => {
    expect(rawFailureFields("一句话", "兜底")).toEqual({ summary: "一句话", detail: null, fix: null, copyText: "一句话" });
    const two = rawFailureFields("Timeout 30000ms exceeded.\n== logs ==\nwaiting for button", "兜底");
    expect(two.summary).toBe("Timeout 30000ms exceeded.");
    expect(two.detail).toContain("waiting for button");
    const long = rawFailureFields("x".repeat(400), "兜底");
    expect(long.summary.length).toBe(160);
    expect(long.summary.endsWith("…")).toBe(true);
    expect(long.detail).toBe("x".repeat(400));
    expect(rawFailureFields("  ", "兜底").summary).toBe("兜底");
  });
});
