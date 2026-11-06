/** @vitest-environment jsdom */
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { SidebarShortcutButtons } from "@/features/shell/SidebarShortcutButtons";

import { setSidebarShortcuts, shortcutForView } from "./sidebarShortcuts";

const containerOf = (element: HTMLElement) => element.closest("[data-sidebar-shortcuts]") as HTMLElement;

vi.mock("@/app/preferences", () => ({ useI18n: () => (key: string) => key }));

describe("侧栏快捷方式", () => {
  beforeEach(() => {
    localStorage.clear();
    setSidebarShortcuts([]);
  });
  afterEach(cleanup);

  it("按存储里的顺序摆成图标键,点了走同一个页面切换", () => {
    setSidebarShortcuts([shortcutForView("media"), shortcutForView("workflows")]);
    const onViewChange = vi.fn();
    render(<SidebarShortcutButtons workspaceId="w1" onViewChange={onViewChange} />);

    const buttons = screen.getAllByRole("button");
    expect(buttons.map((one) => one.getAttribute("aria-label"))).toEqual(["navMedia", "navWorkflows"]);
    fireEvent.click(buttons[0]);
    expect(onViewChange).toHaveBeenCalledWith("media");
    expect(containerOf(buttons[0]).style.gridTemplateColumns, "两个快捷方式就两列").toBe("repeat(2, minmax(0, 1fr))");
  });

  it("只有一个时占满一整行,三个时三等分", () => {
    setSidebarShortcuts([shortcutForView("media")]);
    render(<SidebarShortcutButtons workspaceId="w1" onViewChange={vi.fn()} />);
    expect(containerOf(screen.getByRole("button")).style.gridTemplateColumns).toBe("repeat(1, minmax(0, 1fr))");
    cleanup();

    setSidebarShortcuts([shortcutForView("media"), shortcutForView("workflows"), shortcutForView("plugins")]);
    render(<SidebarShortcutButtons workspaceId="w1" onViewChange={vi.fn()} />);
    expect(containerOf(screen.getAllByRole("button")[0]).style.gridTemplateColumns).toBe("repeat(3, minmax(0, 1fr))");
  });

  it("没有配置时不占侧栏的位置", () => {
    const { container } = render(<SidebarShortcutButtons workspaceId="w1" onViewChange={vi.fn()} />);
    expect(container.firstElementChild).toBeNull();
  });
});
