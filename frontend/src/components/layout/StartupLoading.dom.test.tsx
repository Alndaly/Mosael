/** @vitest-environment jsdom */
import "@testing-library/jest-dom/vitest";
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { StartupLoading } from "./StartupLoading";

describe("StartupLoading", () => {
  it("用可访问的忙碌状态呈现启动进度", () => {
    const { container } = render(
      <StartupLoading label="正在连接后端" detail="正在等待服务响应，请稍候" />,
    );

    const status = screen.getByRole("status");
    expect(status).toHaveAttribute("aria-live", "polite");
    expect(status).toHaveAttribute("aria-busy", "true");
    expect(status).toHaveTextContent("正在连接后端");
    expect(status).toHaveTextContent("正在等待服务响应，请稍候");
    expect(container.querySelector(".animate-openstudio-spin")).toBeTruthy();
  });
});
