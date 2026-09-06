import { describe, expect, it } from "vitest";
import { canonicalSourceUrl, collectCitations } from "./citations";
import type { AgentTimelineItem } from "./ToolCalls";
const tool = (name: string, result: unknown, status: "done" | "error" = "done"): AgentTimelineItem => ({type: "tool", tool: {id: name, name, result, status}});
describe("source citations", () => {
  it("only promotes successful source tool results, with pi and MCP envelopes", () => {
    const citations = collectCitations([
      tool("web_search", {details: {data: [{title: "Docs", url: "https://example.org/docs", snippet: "Evidence"}]}}),
      tool("fetch_url", {content: [{type: "text", text: JSON.stringify({title: "Article", url: "https://example.org/article", text: "Full text"})}]}),
      tool("read_note", {id: "n1", title: "采访", revision: 2, markdown: "原话", citation_url: "#/notes?note=n1&revision=2"}),
      tool("fetch_url", {url: "https://failed.example/"}, "error"),
      tool("run_code", {url: "https://untrusted.example/"}),
    ]);
    expect(citations.size).toBe(3);
    expect(citations.get("#/notes?note=n1&revision=2")?.excerpt).toBe("原话");
    expect(citations.get("https://example.org/docs")?.label).toBe("example.org");
  });
  it("rejects executable, credential-bearing and malformed citation URLs", () => {
    for (const url of ["javascript:alert(1)", "data:text/html,test", "https://user:pass@example.org", "#/notes?note=x", "file:///tmp/a"])
      expect(canonicalSourceUrl(url)).toBeNull();
  });
});
