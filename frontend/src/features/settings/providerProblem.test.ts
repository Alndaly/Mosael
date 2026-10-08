import { describe, expect, it } from "vitest";

import type { ProviderProfile } from "@/api/client";
import { providerProblem } from "./providerProblem";

const profile = (patch: Partial<ProviderProfile>): ProviderProfile =>
  ({ id: "p", name: "Kimi", vendor: "kimi", enabled: true, auth_type: "api_key", key_hint: "…abcd", is_mine: true, oauth_linked: false, oauth_expired: false, ...patch }) as ProviderProfile;

//: 体检 UM-23:连接列表和默认模型那一行用同一份「这条连接对我现在能不能用」。
describe("这条连接对我现在能不能用", () => {
  it("说得出是哪一种用不了", () => {
    expect(providerProblem(profile({}))).toBeNull();
    expect(providerProblem(profile({ enabled: false }))).toBe("disabled");
    expect(providerProblem(profile({ key_hint: "", is_mine: false }))).toBe("noKey");
    expect(providerProblem(profile({ auth_type: "oauth", key_hint: "", oauth_linked: false }))).toBe("unauthorized");
    expect(providerProblem(profile({ auth_type: "oauth", oauth_linked: true, oauth_expired: true }))).toBe("expired");
    expect(providerProblem(profile({ auth_type: "oauth", oauth_linked: true }))).toBeNull();
  });

  it("插件管着的连接钥匙在插件实例上,这里不判", () => {
    expect(providerProblem(profile({ key_hint: "", is_mine: false, plugin_instance_id: "inst" }))).toBeNull();
  });

  it("存了一份空钥匙(本机 Ollama 这类不要钥匙的端点)照样算能用 —— 和后端放不放行同一个判据", () => {
    expect(providerProblem(profile({ key_hint: "", is_mine: true }))).toBeNull();
  });
});
