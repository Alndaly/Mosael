import { describe, expect, it } from "vitest";

import { chatProfileIds, generationVendors, type ChatProfileLike } from "./bindingReadiness";

describe("chatProfileIds:LLM 节点能用哪些连接", () => {
  const profile = (over: Partial<ChatProfileLike>): ChatProfileLike => ({
    id: "p", enabled: true, auth_type: "api_key", oauth_linked: false, base_url: "https://x", ...over,
  });

  it("只认能跑自动化对话的连接:停用的、没地址的、没连上的 OAuth 都不算", () => {
    const ids = chatProfileIds([
      profile({ id: "ok" }),
      profile({ id: "off", enabled: false }),
      profile({ id: "no-url", base_url: " " }),
      profile({ id: "oauth-unlinked", auth_type: "oauth", base_url: "" }),
      profile({ id: "oauth-linked", auth_type: "oauth", oauth_linked: true, base_url: "" }),
    ]);
    expect([...ids].sort()).toEqual(["oauth-linked", "ok"]);
  });
});

describe("generationVendors:生成节点的服务商配没配", () => {
  it("按后端给的可用生成模型算,和 AI 工作台同源;各种生成(含音频)一视同仁", () => {
    const vendors = generationVendors([
      { provider: "suno" },
      { provider: "kling" },
      { provider: "kling" },
    ]);
    expect([...vendors].sort()).toEqual(["kling", "suno"]);
  });

  it("连接开着但模型全停用:后端不列它的模型,这里也就不算配好", () => {
    expect(generationVendors([]).size).toBe(0);
  });
});
