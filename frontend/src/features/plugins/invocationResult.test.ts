import { describe, expect, it } from "vitest";

import { formatInvocationResult, unwrapEncodedJson } from "./invocationResult";

describe("调用记录的输出", () => {
  it("展开被编码成字符串的 JSON —— 中文不再是 \\u 转义", () => {
    // 截图里那一屏的真实形状:FastMCP 把字符串返回值包进 result,内层是 ensure_ascii 的 JSON。
    const raw = { result: JSON.stringify({ name: "Mosael · 三间展厅 · 运镜练习", object_count: 49 }) };
    const text = formatInvocationResult(raw);
    expect(text).toContain("三间展厅");          // 而不是 三间展厅
    expect(text).not.toContain("\\u");
    expect(text).not.toContain('\\"');            // 内层不再被二次转义
    expect(JSON.parse(text).result.object_count).toBe(49);
  });

  it("嵌套的对象和数组一起展开", () => {
    const raw = { result: JSON.stringify({ objects: [{ name: "Mesh_0", location: [0, 0, -0.04] }] }) };
    const value = unwrapEncodedJson(raw) as { result: { objects: { location: number[] }[] } };
    expect(value.result.objects[0].location).toEqual([0, 0, -0.04]);
  });

  it("普通文本原样保留,不被当成 JSON", () => {
    expect(formatInvocationResult({ text: "Blender 未响应,请检查 Add-on 连接。" }))
      .toContain("Blender 未响应");
  });

  it("整条输出就是一句话时不套引号", () => {
    // 工具返回一句给人看的话,不该显示成 "……" 带引号的 JSON 字符串。
    expect(formatInvocationResult("已连接到 Blender 5.2.0")).toBe("已连接到 Blender 5.2.0");
  });

  it("看着像 JSON 但解不动的字符串不吞掉", () => {
    const broken = "{ 这不是 JSON";
    expect(unwrapEncodedJson({ result: broken })).toEqual({ result: broken });
  });

  it("不把数字样的字符串变成数字 —— 展示层不改数据类型", () => {
    // "9876" 是端口号。变成 9876 会让人以为上游返回的就是数字。
    expect(unwrapEncodedJson({ BLENDER_PORT: "9876" })).toEqual({ BLENDER_PORT: "9876" });
    expect(unwrapEncodedJson({ ok: "true" })).toEqual({ ok: "true" });
  });

  it("嵌套过深时停下,不无限展开", () => {
    let payload = '{"end":1}';
    for (let i = 0; i < 12; i += 1) payload = JSON.stringify({ next: payload });
    expect(() => formatInvocationResult(payload)).not.toThrow();
  });

  it("超长字符串不去试解析", () => {
    const huge = `{${"x".repeat(200_001)}}`;
    expect(unwrapEncodedJson({ log: huge })).toEqual({ log: huge });
  });
});
