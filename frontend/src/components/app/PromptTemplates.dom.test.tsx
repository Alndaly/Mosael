/** @vitest-environment jsdom */
import React from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";

vi.mock("@/app/preferences", () => ({ useI18n: () => (key: string) => key }));

import { messages } from "@/app/messages";
import { PROMPT_TEMPLATE_GROUPS, PromptTemplateButton, withTemplate } from "./PromptTemplates";

it("挑一组、点一张模板,交出的是正文;写了东西的提示词接在后面,不替人删掉", () => {
  const onPick = vi.fn();
  render(<PromptTemplateButton onPick={onPick} />);
  fireEvent.click(screen.getByRole("button", { name: "promptTemplates" }));
  fireEvent.click(screen.getByRole("tab", { name: "promptTplGroupGrid" }));
  fireEvent.click(document.querySelector<HTMLElement>("[data-prompt-template='stickers']")!);
  expect(onPick).toHaveBeenCalledWith("promptTplStickers");
  expect(withTemplate("", "B")).toBe("B");
  expect(withTemplate("A  ", "B")).toBe("A\nB");
});

it("每一条模板中英文案都在", () => {
  for (const locale of ["zh-CN", "en-US"] as const) {
    const table = messages[locale] as Record<string, string>;
    for (const group of PROMPT_TEMPLATE_GROUPS) {
      expect(table[group.label]).toBeTruthy();
      for (const one of group.templates) expect(table[one.title] && table[one.prompt]).toBeTruthy();
    }
  }
});
