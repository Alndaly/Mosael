/** @vitest-environment jsdom */
import { render, screen } from "@testing-library/react";
import React from "react";
import { beforeAll, describe, expect, it, vi } from "vitest";

vi.mock("@/app/preferences", () => ({
  useI18n: () => (key: string) => key,
  usePreferences: () => ({ locale: "zh-CN" }),
}));

import { TooltipProvider } from "@/components/ui/tooltip";
import { ListField } from "@/features/nodeForms/ListField";

beforeAll(() => {
  vi.stubGlobal("ResizeObserver", class { observe() {} unobserve() {} disconnect() {} });
});

function renderList(value: unknown) {
  return render(
    <TooltipProvider>
      <ListField value={value} variables={[]} onChange={() => {}} />
    </TooltipProvider>,
  );
}

describe("一串值的编辑器", () => {
  it("存着「名字 → 值」的映射(没迁移到的旧写法):说出来,而不是一片空白像没填", () => {
    // 运行时这一格会报「要的是一串值」(后端 plugins.inputs._as_list);表单上空着看不出哪里不对。
    renderList({ a: "第一段", b: "第二段" });
    expect(screen.getByRole("note").textContent).toBe("wfListGotMapping");
  });

  it("存的是数组时不说", () => {
    renderList(["第一段"]);
    expect(screen.queryByRole("note")).toBeNull();
  });
});
