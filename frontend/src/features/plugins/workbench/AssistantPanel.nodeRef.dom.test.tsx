/** @vitest-environment jsdom */
import React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { PreferencesProvider } from "@/app/preferences";
import { AgentMarkdown } from "@/components/markdown/Markdown";
import { MarkdownRefsContext } from "@/components/markdown/markdownRefs";
import { TooltipProvider } from "@/components/ui/tooltip";
import { NODE_REFS } from "./AssistantPanel";

describe("ComfyUI 助手回复里的节点引用", () => {
  it("悬停 #12 出定位说明 —— Hint 收到的是真实 DOM 锚点，不是 Fragment", async () => {
    render(
      <QueryClientProvider client={new QueryClient()}>
      <PreferencesProvider>
        <TooltipProvider delayDuration={0}>
          <MarkdownRefsContext.Provider value={NODE_REFS}>
            <AgentMarkdown>{"看 #12 这个节点，网站是 [civitai.com](https://civitai.com/models/1)"}</AgentMarkdown>
          </MarkdownRefsContext.Provider>
        </TooltipProvider>
      </PreferencesProvider>
      </QueryClientProvider>,
    );

    const ref = document.querySelector<HTMLButtonElement>('[data-comfy-node="12"]');
    expect(ref).not.toBeNull();
    expect(ref!.getAttribute("aria-label")).toContain("#12");

    fireEvent.pointerEnter(ref!);
    fireEvent.pointerMove(ref!);
    const tooltip = await screen.findByRole("tooltip");
    expect(tooltip.textContent).toContain("#12");
    expect(tooltip.textContent).toContain("定位");

    const website = screen.getByRole("link", { name: "civitai.com" });
    fireEvent.pointerEnter(website);
    fireEvent.pointerMove(website);
    const websiteTooltip = await screen.findByRole("tooltip");
    expect(websiteTooltip.textContent).toContain("https://civitai.com/models/1");
  });
});
