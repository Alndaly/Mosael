/** @vitest-environment jsdom */
/**
 * 导入弹窗中间那块表单:**一行一件事,每行占满内容宽**。
 *
 * 维护者:「这里中间这一块儿排版表单设计有点怪异」。此前 `sm:grid-cols-2` 把这块切成两列:改名输入框
 * 只占半行、右边空一大块,两个勾选挤在第二列里、靠 `pt-6` 硬凑到和左列标签齐平;显示名和装进去的名字
 * 相同时,屏幕上同一个名字写两遍。
 *
 * 「占满内容宽」怎么断:jsdom 不排版,见 `test/rowWidth.ts` —— 按声明的轨道数算这一行占内容宽的几分之几,
 * 1 就是满宽。断的是「有没有把这一行切小」,不是类名字符串长什么样。
 */
import React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { AgentSkillImport, AgentSkillImportItem } from "@/api/client";

const api = vi.hoisted(() => ({ commitSkillImport: vi.fn() }));
vi.mock("@/api/client", () => api);
vi.mock("@/app/preferences", async () => {
  const { messages } = await import("@/app/messages");
  return {
    useI18n: () => (key: string) => (messages["zh-CN"] as Record<string, string>)[key] ?? key,
    usePreferences: () => ({ locale: "zh-CN" }),
  };
});

import { messages } from "@/app/messages";
import { SkillImportDialog } from "@/features/agent/skills/SkillImportDialog";
import { widthShare } from "@/test/rowWidth";

const zh = messages["zh-CN"] as Record<string, string>;

/** 一条暂存的导入技能。默认那份:文件里**不写**名字,免得它混进「名字写了几遍」的计数。 */
function item(over: Partial<AgentSkillImportItem> = {}): AgentSkillImportItem {
  return {
    name: "ad-cuts",
    title: "",
    description: "把长视频剪成广告片",
    license: "",
    compatibility: "",
    allowed_tools: "",
    unknown_fields: [],
    folder: "",
    conflict: "",
    files: [{ path: "SKILL.md", size: 12, script: false, binary: false, text: "剪成广告片的做法。\n" }],
    ...over,
  };
}

function renderDialog(...skills: AgentSkillImportItem[]) {
  const staged: AgentSkillImport = { import_id: "imp-1", source_name: "skills.zip", skills };
  return render(
    <QueryClientProvider client={new QueryClient()}>
      <SkillImportDialog workspaceId="w-1" staged={staged} onClose={() => {}} />
    </QueryClientProvider>,
  );
}

const content = () => document.querySelector<HTMLElement>('[data-slot="modal-body"]')!;
const section = () => document.querySelector<HTMLElement>('[data-import-skill="ad-cuts"]')!;
const renameInput = () => screen.getByPlaceholderText("ad-cuts");

function occurrences(haystack: string, needle: string): number {
  return haystack.split(needle).length - 1;
}

describe("导入弹窗的表单:一行一件事,每行满宽", () => {
  it("改名输入框(和它所在的那一行)占满内容宽,不再被切成半行", () => {
    renderDialog(item({ title: "做带货短视频", conflict: "workspace" }));
    const field = renameInput().parentElement as HTMLElement; // DIALOG_FIELD 那个 label
    expect(widthShare(field, content()), "改名字段那一行只占了内容宽的一半").toBe(1);
    expect(widthShare(renameInput(), content()), "改名输入框没占满它那一行").toBe(1);
  });

  it("两个勾选各自一行、整行可点,不再挤在第二列里", () => {
    renderDialog(item({ title: "做带货短视频", conflict: "workspace" }));
    const enable = section().querySelector<HTMLElement>('[data-slot="import-enable"]')!;
    const replace = within(section()).getByText(zh.agentSkillsImportReplace).closest("label") as HTMLElement;
    expect(widthShare(enable.parentElement as HTMLElement, content()), "勾选那一块又被横向切开了").toBe(1);
    expect(widthShare(replace, content()), "「替换」这一行不满宽").toBe(1);
    expect(widthShare(enable, content()), "「装好就启用」这一行不满宽 —— 点不到整行").toBe(1);
    // 改名和勾选不再挤在同一层里并排:改名字段自己就是一条满宽的行。
    const field = renameInput().parentElement as HTMLElement;
    expect(field.parentElement).not.toBe(enable.parentElement);
    expect(widthShare(field, content())).toBe(1);
  });
});

describe("名字别写两遍", () => {
  it("显示名和装进去的名字相同时只写一遍", () => {
    renderDialog(item({ title: "ad-cuts" }));
    expect(occurrences(section().textContent ?? "", "ad-cuts")).toBe(1);
  });

  it("两个名字不同时都写出来,并且说清哪个是装进去的名字", () => {
    renderDialog(item({ title: "做带货短视频" }));
    const text = section().textContent ?? "";
    expect(text).toContain("做带货短视频");
    const named = section().querySelector<HTMLElement>('[data-slot="import-skill-name"]');
    expect(named, "另一个名字没跟着说清它是什么").not.toBeNull();
    expect(named!.textContent).toContain("ad-cuts");
    const label = zh.agentSkillsImportInstalledAs;
    expect(label, "还没有一句说明「装进去的名字」").toBeTruthy();
    expect(named!.textContent).toContain(label);
  });
});

describe("既有行为一条不减", () => {
  it("改名 / 替换 / 启用一起带走,钩子还在", async () => {
    api.commitSkillImport.mockResolvedValue([]);
    renderDialog(item({ conflict: "workspace" }));
    expect(section()).toHaveAttribute("data-import-skill", "ad-cuts");
    expect(section().querySelector('[data-slot="import-enable"]')).not.toBeNull();

    fireEvent.change(renameInput(), { target: { value: "my-cuts" } });
    fireEvent.click(screen.getByRole("checkbox", { name: zh.agentSkillsImportReplace }));
    fireEvent.click(screen.getByRole("checkbox", { name: zh.agentSkillsImportEnable }));
    fireEvent.click(screen.getByRole("button", { name: zh.agentSkillsImportConfirm }));

    await waitFor(() =>
      expect(api.commitSkillImport).toHaveBeenCalledWith("w-1", "imp-1", [
        { name: "ad-cuts", rename_to: "my-cuts", replace: true, enable: true },
      ]),
    );
  });

  it("撞名没改名时照旧拦住:提示在改名字段下面,导入键按不动", () => {
    renderDialog(item({ conflict: "builtin" }));
    expect(renameInput()).toHaveValue("ad-cuts-imported");
    fireEvent.change(renameInput(), { target: { value: "" } });
    expect(within(section()).getByText(zh.agentSkillsImportConflictBuiltin)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: zh.agentSkillsImportConfirm })).toBeDisabled();
  });

  it("名字不合法时提示照旧", () => {
    renderDialog(item({ conflict: "workspace" }));
    fireEvent.change(renameInput(), { target: { value: "Bad Name" } });
    expect(within(section()).getByText(zh.agentSkillsFieldNameInvalid)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: zh.agentSkillsImportConfirm })).toBeDisabled();
  });

  it("不勾「导入这个技能」时改名和勾选都收起来", () => {
    renderDialog(item({ conflict: "workspace" }));
    fireEvent.click(screen.getByRole("checkbox", { name: zh.agentSkillsImportInclude }));
    expect(screen.queryByPlaceholderText("ad-cuts")).toBeNull();
    expect(section().querySelector('[data-slot="import-enable"]')).toBeNull();
    expect(screen.getByRole("button", { name: zh.agentSkillsImportConfirm })).toBeDisabled();
  });
});
