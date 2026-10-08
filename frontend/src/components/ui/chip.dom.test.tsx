/** @vitest-environment jsdom */

/** 胶囊筛选:高 28(和 xs 对齐)、全圆、12px 字;选中强调底色。选中的语义跟着这一排当什么读。 */
import React from "react";
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import { Chip } from "@/components/ui/chip";
import { CONTROL_HEIGHT } from "@/components/ui/control-size";

afterEach(cleanup);

describe("胶囊筛选", () => {
  it("28px、全圆、12px 字;选中的强调底色", () => {
    render(
      <>
        <Chip selected>全部</Chip>
        <Chip selected={false}>图像</Chip>
      </>,
    );
    const [all, image] = screen.getAllByRole("button");
    for (const chip of [all, image]) expect(chip.className.split(/\s+/)).toEqual(expect.arrayContaining([CONTROL_HEIGHT.xs, "rounded-full", "text-ui-xs"]));
    expect(all.className.split(/\s+/)).toContain("bg-accent");
    expect(image.className.split(/\s+/)).not.toContain("bg-accent");
  });

  it("默认是切换按钮(aria-pressed);当页签读给 role=tab(aria-selected),当单选读给 role=radio(aria-checked)", () => {
    render(
      <>
        <Chip selected>多选</Chip>
        <Chip selected role="tab">页签</Chip>
        <Chip selected role="radio">单选</Chip>
      </>,
    );
    expect(screen.getByRole("button", { name: "多选" }).getAttribute("aria-pressed")).toBe("true");
    expect(screen.getByRole("tab", { name: "页签" }).getAttribute("aria-selected")).toBe("true");
    expect(screen.getByRole("radio", { name: "单选" }).getAttribute("aria-checked")).toBe("true");
    expect(screen.getByRole("tab", { name: "页签" }).hasAttribute("aria-pressed")).toBe(false);
  });
});
