/** @vitest-environment jsdom */
import React from "react";
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import {
  SettingsBlock,
  SettingsBlockTitle,
  SettingsGroup,
  SettingsList,
  SettingsListBlock,
  SettingsListItem,
  SettingsRow,
  SettingsSectionStack,
} from "./ui";

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
    expect(header).toHaveClass("pb-4");
    expect(content).not.toHaveClass("rounded-lg");
    expect(content).not.toHaveClass("border");
    expect(content).not.toHaveClass("bg-panel");
  });

  it("puts each section divider against the previous content and spaces the next header", () => {
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
    const separators = container.querySelectorAll('[data-slot="separator"]');
    expect(separators).toHaveLength(2);
    separators.forEach((separator) => {
      expect(separator).toHaveClass("mb-3");
      expect(separator).not.toHaveClass("mt-3", "my-3");
    });
  });

  it("keeps rows and flat-list items on the same 12px vertical rhythm", () => {
    const { container } = render(
      <SettingsGroup title="模型">
        <SettingsRow label="默认模型">K3</SettingsRow>
        <SettingsList>
          <SettingsListItem>供应商 A</SettingsListItem>
        </SettingsList>
      </SettingsGroup>,
    );

    expect(container.querySelector('[data-slot="settings-row"]')).toHaveClass("py-3");
    expect(container.querySelector('[data-slot="settings-list-item"]')).toHaveClass("py-3");
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

  it("gives pure list sections a single vertical spacing owner", () => {
    const { container } = render(
      <SettingsListBlock>
        <SettingsListItem>飞书机器人</SettingsListItem>
      </SettingsListBlock>,
    );

    const block = container.querySelector('[data-slot="settings-list-block"]');
    expect(block).toBeInTheDocument();
    expect(block?.className).not.toMatch(/\bpy-/);
    expect(block?.querySelector('[data-slot="settings-list-item"]')).toHaveClass("py-3");
  });

  it("keeps optional list tools inside the same spacing contract", () => {
    const { container } = render(
      <SettingsListBlock toolbar={<div>已选择 2 项</div>}>
        <SettingsListItem>成本规则</SettingsListItem>
      </SettingsListBlock>,
    );

    expect(container.querySelector('[data-slot="settings-list-toolbar"]')).toHaveClass("px-0.5", "pt-3");
    expect(container.querySelector('[data-slot="settings-list-block"]')?.className).not.toMatch(/\bpy-/);
  });

  it("can bound a long settings list and scroll it internally", () => {
    const { container } = render(
      <SettingsList scrollable>
        <SettingsListItem>团队动态</SettingsListItem>
      </SettingsList>,
    );

    expect(container.firstElementChild).toHaveClass("max-h-80", "overflow-y-auto", "overscroll-contain");
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

  it("lets the block own the distance between its title and content", () => {
    const { container } = render(
      <SettingsBlock>
        <SettingsBlockTitle>团队动态</SettingsBlockTitle>
        <SettingsList>
          <SettingsListItem>创建了画板</SettingsListItem>
        </SettingsList>
      </SettingsBlock>,
    );

    expect(container.querySelector('[data-slot="settings-block"]')).toHaveClass("gap-2", "py-3");
    const title = container.querySelector('[data-slot="settings-block-title"]');
    expect(title).toHaveClass("m-0");
    expect(title?.className).not.toMatch(/m[tyb]-/);
  });
});
