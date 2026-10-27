/** @vitest-environment jsdom */
import React from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { PreferencesProvider } from "@/app/preferences";
import { CitationContext } from "@/components/markdown/CitationLink";
import { AgentMarkdown } from "@/components/markdown/Markdown";
import { MarkdownRefsContext } from "@/components/markdown/markdownRefs";
import { HintRegion, TooltipProvider } from "@/components/ui/tooltip";
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

  it("有结构化来源的网站胶囊悬停显示标题、摘录和网址", async () => {
    const href = "https://civitai.com/models/1";
    render(
      <QueryClientProvider client={new QueryClient()}>
        <PreferencesProvider>
          <HintRegion.Provider value={{ side: "top", layer: "dom" }}>
          <TooltipProvider delayDuration={0}>
            <CitationContext.Provider value={new Map([[href, {
              href, title: "模型页", label: "civitai.com", kind: "web", excerpt: "作者 catlover1937",
            }]])}>
              <AgentMarkdown>{"[civitai.com](https://civitai.com/models/1)"}</AgentMarkdown>
            </CitationContext.Provider>
          </TooltipProvider>
          </HintRegion.Provider>
        </PreferencesProvider>
      </QueryClientProvider>,
    );
    const website = screen.getByRole("link", { name: "模型页" });
    fireEvent.pointerEnter(website);
    fireEvent.pointerMove(website);
    const tooltip = await screen.findByRole("tooltip");
    expect(tooltip.textContent).toContain("作者 catlover1937");
    expect(tooltip.textContent).toContain(href);
  });
});
