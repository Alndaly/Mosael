/** @vitest-environment jsdom */
/**
 * 技能编辑器弹窗的字段:**每个字段各占一行,每行满宽**(和导入弹窗同一条标准)。
 *
 * 维护者:「同一行内尽量满宽」。这两个字段组此前是 `sm:grid-cols-2`:720px 的弹窗里每个输入框只有
 * 329px,说明文字在窄框里折行、参差不齐,而整条标准在仓库里只此三处(另一处在导入弹窗里,已修)。
 *
 * 断法见 `test/rowWidth.ts`:jsdom 不排版,按声明的轨道数算这一行占内容宽的几分之几,1 就是满宽。
 */
import React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

const api = vi.hoisted(() => ({
  createSkill: vi.fn(),
  deleteSkillFile: vi.fn(),
  getSkill: vi.fn(),
  putSkillFile: vi.fn(),
  updateSkill: vi.fn(),
}));
vi.mock("@/api/client", () => api);
vi.mock("@/app/preferences", () => ({
  useI18n: () => (key: string) => key,
  usePreferences: () => ({ locale: "zh-CN" }),
}));

import { SkillEditorDialog } from "@/features/agent/skills/SkillEditorDialog";
import { widthShare } from "@/test/rowWidth";

describe("编辑器弹窗的字段", () => {
  it("每个字段各占一行、占满内容宽", () => {
    render(
      <QueryClientProvider client={new QueryClient()}>
        <SkillEditorDialog workspaceId="w-1" target={{ kind: "create" }} onClose={() => {}} />
      </QueryClientProvider>,
    );
    const content = document.querySelector<HTMLElement>('[data-slot="modal-body"]')!;
    const labels = [...content.querySelectorAll<HTMLElement>("label")];
    expect(labels.length, "字段没画出来").toBeGreaterThanOrEqual(4);
    const shares = labels.map((label) => widthShare(label, content));
    expect(shares, "有字段被挤成了半行").toEqual(shares.map(() => 1));
  });
});
