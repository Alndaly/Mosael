/** @vitest-environment jsdom */
import React from "react";
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { SettingsGroup, SettingsList, SettingsListItem, SettingsRow, SettingsSectionStack } from "./ui";

describe("settings section layout", () => {
  it("keeps groups flat inside the page panel", () => {
    const { container } = render(
      <SettingsGroup title="外观">
        <SettingsRow label="主题">深色</SettingsRow>
      </SettingsGroup>,
    );

    const content = container.querySelector('[data-slot="settings-group-content"]');
    const header = container.querySelector('[data-slot="settings-group-header"]');
    expect(content).not.toBeNull();
    expect(header).toHaveClass("border-b");
    expect(content).not.toHaveClass("rounded-lg");
    expect(content).not.toHaveClass("border");
    expect(content).not.toHaveClass("bg-panel");
  });

  it("uses separators rather than cards between sibling sections", () => {
    const { container } = render(
      <SettingsSectionStack>
        <SettingsGroup title="外观" />
        <>
          <SettingsGroup title="背景" />
          <SettingsGroup title="自定义 CSS" />
        </>
      </SettingsSectionStack>,
    );

    expect(screen.getAllByRole("heading")).toHaveLength(3);
    expect(container.querySelectorAll('[data-slot="separator"]')).toHaveLength(2);
  });

  it("gives the page, section, and row copy distinct typography levels", () => {
    const { container } = render(
      <SettingsSectionStack>
        <SettingsGroup title="外观" description="界面主题与语言">
          <SettingsRow label="主题" description="跟随系统自动切换">
            深色
          </SettingsRow>
        </SettingsGroup>
        <SettingsGroup title="背景与磨玻璃" />
      </SettingsSectionStack>,
    );

    const stack = container.querySelector('[data-slot="settings-section-stack"]');
    const titles = container.querySelectorAll('[data-slot="settings-group-title"]');
    const rowLabel = container.querySelector('[data-slot="settings-row-label"]');
    const rowDescription = container.querySelector('[data-slot="settings-row-description"]');

    expect(stack?.className).toContain("first-child_[data-slot=settings-group-title]");
    expect(titles[0]).toHaveClass("text-[18px]");
    expect(titles[1]).toHaveClass("text-[18px]");
    expect(rowLabel).toHaveClass("text-[15px]", "font-semibold");
    expect(rowDescription).toHaveClass("text-ui-sm", "leading-[1.5]");
  });

  it("renders settings collections as divided flat rows", () => {
    const { container } = render(
      <SettingsList>
        <SettingsListItem>供应商 A</SettingsListItem>
        <SettingsListItem>供应商 B</SettingsListItem>
      </SettingsList>,
    );

    const list = container.firstElementChild;
    expect(list).toHaveClass("divide-y");
    expect(list?.firstElementChild).not.toHaveClass("border");
    expect(list?.firstElementChild).not.toHaveClass("rounded-md");
  });

  it("lets a single-section empty state fill the settings pane", () => {
    const { container } = render(
      <SettingsSectionStack>
        <SettingsGroup title="飞书机器人" contentClassName="min-h-0">
          <div>empty</div>
        </SettingsGroup>
      </SettingsSectionStack>,
    );

    expect(container.querySelector('[data-slot="settings-section-stack"]')).toHaveClass("h-full");
    expect(container.querySelector('[data-slot="settings-group"]')).toHaveClass("grid");
    expect(container.querySelector('[data-slot="settings-group-content"]')).toHaveClass("min-h-0");
  });
});
