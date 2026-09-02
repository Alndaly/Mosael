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
