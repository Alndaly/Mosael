import { describe, expect, it } from "vitest";

import contract from "../../../../contracts/workflow-field-activation.json";

import {
  isOneOfFallback,
  isPureReference,
  isTakenByOneOfPeer,
  isWorkflowFieldActive,
  oneOfGroups,
  oneOfOverfilled,
} from "@/features/nodeForms/fieldActivation";

describe("isWorkflowFieldActive", () => {
  const specs = {
    engine: { default: "google" },
    profile_id: { active_when: { engine: "ai" } },
  };

  it("无条件字段始终参与", () => {
    expect(isWorkflowFieldActive(specs.engine, {}, specs)).toBe(true);
  });

  it("按当前配置决定字段是否参与", () => {
    expect(isWorkflowFieldActive(specs.profile_id, { engine: "google" }, specs)).toBe(false);
    expect(isWorkflowFieldActive(specs.profile_id, { engine: "ai" }, specs)).toBe(true);
  });

  it("父字段未保存时读取声明默认值", () => {
    expect(isWorkflowFieldActive(specs.profile_id, {}, specs)).toBe(false);
  });

  it("支持一个条件允许多个取值", () => {
    const spec = { active_when: { engine: ["ai", "local"] } };
    expect(isWorkflowFieldActive(spec, { engine: "local" }, specs)).toBe(true);
  });

  it.each(contract.cases)("与后端共享契约：$name", ({ spec, config, specs, active }) => {
    expect(isWorkflowFieldActive(spec, config, specs)).toBe(active);
  });
});

describe("one_of:同组恰好填一个", () => {
  const specs = {
    session: {},
    asset_id: { one_of: "source" },
    file_path: { one_of: "source" },
  };

  it("按组名归拢,顺序是声明的顺序", () => {
    expect(oneOfGroups(specs)).toEqual([["asset_id", "file_path"]]);
  });

  it("一格填了,同组其余的收起来;都空时都在", () => {
    expect(isTakenByOneOfPeer("file_path", specs, { asset_id: "a1" })).toBe(true);
    expect(isTakenByOneOfPeer("asset_id", specs, { asset_id: "a1" })).toBe(false);
    expect(isTakenByOneOfPeer("asset_id", specs, {})).toBe(false);
    expect(isTakenByOneOfPeer("file_path", specs, { asset_id: "  " })).toBe(false);
    expect(isTakenByOneOfPeer("session", specs, { asset_id: "a1" })).toBe(false);
  });

  it("只看排在前面的那几格:后面那格填了字面量,前面这格照样在(可以接上游,把它当兜底)", () => {
    expect(isTakenByOneOfPeer("asset_id", specs, { file_path: "/tmp/x.mp4" })).toBe(false);
  });

  it("前面那格只是引用或接了上游:后面这格照常显示,运行时上游为空就用它", () => {
    //: 运行时同组按声明顺序取第一个非空值。前面那格的值全看上游、可能是空的,后面写死的一格是兜底 ——
    //: 此前接了上游也算「填了」,兜底那格被收起来,这种写法在表单里根本填不出来。
    expect(isTakenByOneOfPeer("file_path", specs, {}, (key) => key === "asset_id")).toBe(false);
    expect(isTakenByOneOfPeer("file_path", specs, { asset_id: "{{up.asset_id}}" })).toBe(false);
    //: 引用里夹着别的字就是字面量:它总有值,后面那格永远用不上。
    expect(isTakenByOneOfPeer("file_path", specs, { asset_id: "a-{{up.asset_id}}" })).toBe(true);
  });

  it("兜底那格标出来:前面填了的都只是引用 / 接了上游,这一格才是兜底", () => {
    expect(isOneOfFallback("file_path", specs, { asset_id: "{{up.asset_id}}" })).toBe(true);
    expect(isOneOfFallback("file_path", specs, {}, (key) => key === "asset_id")).toBe(true);
    expect(isOneOfFallback("file_path", specs, {})).toBe(false);
    expect(isOneOfFallback("file_path", specs, { asset_id: "a1", file_path: "/x" })).toBe(false);
    expect(isOneOfFallback("asset_id", specs, { file_path: "{{up.path}}" })).toBe(false);
    expect(isOneOfFallback("session", specs, { asset_id: "{{up.asset_id}}" })).toBe(false);
  });

  it("纯引用:整格只有一条 {{…}}", () => {
    expect(isPureReference("{{up.sel}}")).toBe(true);
    expect(isPureReference("  {{ up.sel }} ")).toBe(true);
    expect(isPureReference("#{{up.sel}}")).toBe(false);
    expect(isPureReference("{{a.x}}{{b.y}}")).toBe(false);
    expect(isPureReference("")).toBe(false);
  });

  it("两格都已经填了就都留着 —— 藏起来就既看不见也清不掉", () => {
    const both = { asset_id: "a1", file_path: "/tmp/x.mp4" };
    expect(isTakenByOneOfPeer("asset_id", specs, both)).toBe(false);
    expect(isTakenByOneOfPeer("file_path", specs, both)).toBe(false);
  });

  describe("strict 组(one_of_strict:执行器两样都给就报错)照旧恰好一个", () => {
    const strict = {
      asset_id: { one_of: "source", one_of_strict: true },
      file_path: { one_of: "source", one_of_strict: true },
    };
    it("前面接了上游 / 是引用,后面那格照样收起,也不标兜底", () => {
      expect(isTakenByOneOfPeer("file_path", strict, {}, (key) => key === "asset_id")).toBe(true);
      expect(isTakenByOneOfPeer("file_path", strict, { asset_id: "{{up.asset_id}}" })).toBe(true);
      expect(isTakenByOneOfPeer("asset_id", strict, { file_path: "/tmp/x.mp4" })).toBe(true);
      expect(isOneOfFallback("file_path", strict, { asset_id: "{{up.asset_id}}" })).toBe(false);
    });
    it("引用在前、字面量在后也算填了两个", () => {
      expect(oneOfOverfilled(["asset_id", "file_path"], { asset_id: "{{up.asset_id}}", file_path: "/x" }, () => false, true)).toBe(true);
      expect(oneOfOverfilled(["asset_id", "file_path"], { asset_id: "{{up.asset_id}}", file_path: "/x" })).toBe(false);
    });
  });
});
