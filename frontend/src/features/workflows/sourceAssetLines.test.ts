/**
 * 这段文本是用户看不见的东西 —— 界面上是一格一格的角色,配置里是 `id:role` 的行。
 * 翻译错了不会报错:后端拿不到角色就按默认走,于是"我明明挂了尾帧"的片子里没有尾帧。
 */
import { describe, expect, it } from "vitest";

import {
  extraLines,
  parseSourceAssets,
  serializeSourceAssets,
  valueForRole,
  withRole,
} from "@/features/workflows/sourceAssetLines";

describe("解析", () => {
  it("认得出角色", () => {
    expect(parseSourceAssets("a1:first_frame\nb2:last_frame")).toEqual([
      { value: "a1", role: "first_frame" },
      { value: "b2", role: "last_frame" },
    ]);
  });

  it("不写角色就留空_不替它猜一个", () => {
    // 后端有自己的默认(图生视频按首帧、图生图按参考图)。在这里猜等于把那条默认抄第二遍,
    // 两份默认迟早不一致。
    expect(parseSourceAssets("a1")).toEqual([{ value: "a1", role: "" }]);
  });

  it("模板串整条留住_不会被冒号切开", () => {
    expect(parseSourceAssets("{{ai-generate-1.asset_id}}:reference_image")).toEqual([
      { value: "{{ai-generate-1.asset_id}}", role: "reference_image" },
    ]);
  });

  it("后半段不像角色名就不当成角色", () => {
    // `{{a.b:c}}` 这种少见但合法,切开就毁了。
    expect(parseSourceAssets("{{a.b:C1}}")).toEqual([{ value: "{{a.b:C1}}", role: "" }]);
  });

  it("空行和空白丢掉", () => {
    expect(parseSourceAssets("  a1:first_frame  \n\n\n")).toEqual([{ value: "a1", role: "first_frame" }]);
  });
});

describe("往返要稳", () => {
  it("解析再序列化回到原样", () => {
    // 不稳的话,每打开一次检查器配置就被悄悄改一次,diff 里全是噪音。
    const text = "a1:first_frame\nb2:last_frame\nc3";
    expect(serializeSourceAssets(parseSourceAssets(text))).toBe(text);
  });

  it("只有角色没有素材的条目丢掉", () => {
    expect(serializeSourceAssets([{ value: "  ", role: "first_frame" }])).toBe("");
  });
});

describe("按角色改", () => {
  const lines = parseSourceAssets("a1:first_frame\nb2:last_frame");

  it("取得到", () => {
    expect(valueForRole(lines, "last_frame")).toBe("b2");
    expect(valueForRole(lines, "reference_image")).toBe("");
  });

  it("就地替换_不搬家", () => {
    // 删了再追加的话,每改一次顺序就变一次。
    expect(withRole(lines, "first_frame", "z9")).toEqual([
      { value: "z9", role: "first_frame" },
      { value: "b2", role: "last_frame" },
    ]);
  });

  it("清空就删掉那一条", () => {
    expect(withRole(lines, "first_frame", "")).toEqual([{ value: "b2", role: "last_frame" }]);
  });

  it("新角色追加到末尾", () => {
    expect(withRole(lines, "reference_image", "c3")).toHaveLength(3);
  });

  it("清一个本来就没有的角色是空操作", () => {
    expect(withRole(lines, "reference_video", "")).toEqual(lines);
  });
});

describe("认不出的行要留着", () => {
  it("换了模型之后_不再支持的角色不能被悄悄丢掉", () => {
    // 用户换个模型看看效果,回来发现之前挂的东西没了 —— 那比多显示一行难受得多。
    const lines = parseSourceAssets("a1:first_frame\nb2:reference_audio\nc3");
    expect(extraLines(lines, ["first_frame"])).toEqual([
      { value: "b2", role: "reference_audio" },
      { value: "c3", role: "" },
    ]);
  });
});
