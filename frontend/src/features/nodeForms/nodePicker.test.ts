import { describe, expect, it } from "vitest";

import type { WorkflowNodeType } from "@/api/client";
import { nodePickerOptions } from "@/features/nodeForms/nodePicker";

const node = (type: string, extra: Partial<WorkflowNodeType> = {}): WorkflowNodeType =>
  ({ type, label: type, description: `${type} 说明`, category: "内容", ...extra }) as WorkflowNodeType;

describe("添加节点的选项", () => {
  it("保持后端排好的顺序,没分组的落进「其它」", () => {
    const options = nodePickerOptions([node("translate"), node("start", { category: "" })], "其它", (key) => key);
    expect(options.map((option) => [option.value, option.group])).toEqual([
      ["translate", "内容"],
      ["start", "其它"],
    ]);
  });

  it("插件工具点名来自哪个插件,工具名可以搜", () => {
    const [option] = nodePickerOptions(
      [node("plugin.tikhub.fetch_one_video", { plugin_name: "抖音", tool_name: "fetch_one_video", category: "插件" })],
      "其它",
      (key) => key,
    );
    expect(option.description).toBe("抖音 · plugin.tikhub.fetch_one_video 说明");
    expect(option.keywords).toEqual(["fetch_one_video"]);
  });

  it("同一张工作流的完整工作流和表单(ADR 0045):副名说是哪个入口,表单挂在完整工作流下面,按工作流名、路径都搜得到", () => {
    const said: Record<string, string> = { entryFromGroup: "来自 {name}", entryFullWorkflow: "完整工作流" };
    const t = (key: string) => said[key] ?? key;
    const group = { id: "krea2-text-2-image.json", label: "krea2-text-2-image" };
    const [full, form, plain] = nodePickerOptions(
      [
        node("plugin.c.wf_a", { plugin_name: "ComfyUI", tool_name: "wf_a", group: { ...group, entry: "full" } }),
        node("plugin.c.wf_a_app", { plugin_name: "ComfyUI", tool_name: "wf_a_app", group: { ...group, entry: "form" } }),
        node("plugin.c.wf_b", { plugin_name: "ComfyUI", tool_name: "wf_b", group: { id: "b.json", label: "b", entry: "full" } }),
      ],
      "其它",
      t,
    );
    expect(full.description.startsWith("完整工作流 · ComfyUI · ")).toBe(true);
    expect(form.description.startsWith("来自 krea2-text-2-image · ComfyUI · ")).toBe(true);
    expect(plain.description.startsWith("ComfyUI · ")).toBe(true);
    expect([full.indent, form.indent, plain.indent]).toEqual([false, true, false]);
    expect(form.keywords).toEqual(["wf_a_app", "krea2-text-2-image", "krea2-text-2-image.json"]);
  });

  it("副标题是纯文本:说明里的 markdown 记号不露出来", () => {
    const [option] = nodePickerOptions([node("denoise_audio", { description: "产出一份**新素材**" })], "其它", (key) => key);
    expect(option.description).toBe("产出一份新素材");
  });

  it("装了插件之后,泛泛的「插件工具」撤掉;没装时还在", () => {
    const generic = node("plugin_tool");
    expect(nodePickerOptions([generic], "其它", (key) => key).map((option) => option.value)).toEqual(["plugin_tool"]);
    expect(
      nodePickerOptions([generic, node("plugin.x.y", { plugin_name: "X" })], "其它", (key) => key).map((option) => option.value),
    ).toEqual(["plugin.x.y"]);
  });
});
