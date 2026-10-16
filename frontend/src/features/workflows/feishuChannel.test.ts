/**
 * 节点卡上那行「飞书怎么通知」:**「等人确认」此前对它一个字都不说**。
 *
 * 那个门的飞书行为过去完全是隐式的 —— 卡上什么都没写,不点开检查器看不出它会发卡,
 * 更看不出发给谁(发到哪还是运行时按"这次运行从哪来"猜的)。现在这三个问题各有答案:
 * `channel` / `bot` / `to` 写在节点上,卡上那一行说的是**节点上写的那个选择**。
 *
 * 用的都是真的那一份:后端导出的节点目录(`@/test/nodeCatalog`)+ 真的文案表 ——
 * 自己编一份替身的话,"卡上写了什么"和"界面上写了什么"就分家了。
 */
import { readFileSync } from "node:fs";
import { join } from "node:path";

import { describe, expect, it } from "vitest";

import type { WorkflowGraph } from "@/api/client";
import { feishuChannelSummary } from "@/features/workflows/feishuChannel";
import { workflowNodeSubtitle } from "@/features/workflows/workflowCanvasModel";
import { builtinNodeCatalog, uiText } from "@/test/nodeCatalog";

const CATALOGS = { zh: builtinNodeCatalog("zh"), en: builtinNodeCatalog("en") };
type Locale = keyof typeof CATALOGS;

function node(type: string, config: Record<string, unknown> = {}): WorkflowGraph["nodes"][number] {
  return { id: type, type, name: "", config, position: { x: 0, y: 0 } } as WorkflowGraph["nodes"][number];
}

/** 这一版图在这张卡上写着什么(zh 缺省)。 */
function line(type: string, config: Record<string, unknown>, locale: Locale = "zh"): string {
  return workflowNodeSubtitle(node(type, config), CATALOGS[locale], [], uiText(locale));
}

describe("飞书那一行说了什么", () => {
  it("仅站内:明说这一个字都不发飞书", () => {
    expect(line("await_approval", { channel: "none", title: "确认" })).toBe("仅站内");
    expect(line("await_approval", { channel: "none" }, "en")).toBe("In-app only");
  });

  it("哪来发回哪:缺省那一档也写在卡上,而不是空着", () => {
    expect(line("await_approval", { title: "确认" })).toBe("飞书 · 哪来发回哪");
    expect(line("await_approval", { channel: "origin" }, "en")).toBe("Feishu · back to where it came from");
  });

  it("发到某个群:卡上就能看见是哪个群", () => {
    expect(line("await_approval", { channel: "chat", to: "oc_team_room" })).toBe("飞书 · 群 oc_team_room");
    //: id 很长时只放能分辨身份的那一截(卡是张名片,不是日志窗口)。
    expect(line("feishu_message", { channel: "chat", to: "oc_0123456789abcdef0123456789abcdef" })).toBe(
      "飞书 · 群 oc_01234…cdef",
    );
  });

  it("私聊某个人:认得出是谁就写 id,是一段引用就说「发起人」", () => {
    expect(line("await_approval", { channel: "user", to: "ou_bound_person" })).toBe("飞书 · 私聊 ou_bound_person");
    expect(line("await_approval", { channel: "user", to: "{{开始.负责人}}" })).toBe("飞书 · 私聊 发起人");
    expect(line("await_approval", { channel: "user", to: "" })).toBe("飞书 · 私聊 发起人");
  });

  it("手填收件 id:写的是你填的那个 id", () => {
    expect(line("feishu_message", { channel: "raw", raw_id: "ou_someone" })).toBe("飞书 · 发给 ou_someone");
  });

  it("别的节点不掺这一行 —— 只有这两个节点会发飞书", () => {
    expect(feishuChannelSummary("notify", { channel: "none" }, uiText("zh"))).toBe("");
    expect(line("notify", { channel: "none", title: "通知" })).toBe("");
    expect(feishuChannelSummary("feishu_reaction", { channel: "none" }, uiText("zh"))).toBe("");
  });

  it("两种语言都有那一行(不是把 key 原样摆上去)", () => {
    for (const locale of ["zh", "en"] as Locale[]) {
      const text = line("feishu_message", { channel: "none" }, locale);
      expect(text).not.toContain("wfFeishu");
      expect(text.trim()).not.toBe("");
    }
  });
});

describe("这一行真的落到卡片上", () => {
  it("画布节点那一行读的是 workflowNodeSubtitle(不是另一份摘要)", () => {
    //: `configSummary` 是卡片副标题的**唯一**来源(见 WorkflowNode 的 subtitle)。这一处是那条链:
    //: 投影初值给的是 workflowConfigSummary,而注册表到货之后由 useWorkflowDisplayNodes 重算 ——
    //: 飞书那一行在后者里,所以这一句断了卡上就什么都不显示。
    const source = readFileSync(join(import.meta.dirname, "useWorkflowDisplayElements.ts"), "utf8");
    expect(source).toContain("configSummary: workflowNodeSubtitle(");
  });
});
