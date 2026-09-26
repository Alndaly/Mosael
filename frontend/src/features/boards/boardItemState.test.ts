import { describe, expect, it } from "vitest";

import { withSlotProducer, type BoardItem } from "@/api/client";
import { boardSettlementPatch, composerView, itemFormResetKey, itemIsRunning, itemRunStatus, newSlotForm, producerOf, prunedLinksPatch, withProducer } from "./boardItemState";

function image(extra: Partial<BoardItem> = {}): BoardItem {
  return { id: "image-1", kind: "image", x: 0, y: 0, ...extra };
}

describe("画布节点状态", () => {
  it("没有运行态时为空闲", () => {
    expect(itemRunStatus(image())).toBe("idle");
  });

  it("只有带 job id 的排队/运行节点才进入轮询", () => {
    expect(itemIsRunning(image({ run: { status: "running" } }))).toBe(false);
    expect(itemIsRunning(image({ run: { status: "queued", job_id: "job-1" } }))).toBe(true);
    expect(itemIsRunning(image({ run: { status: "succeeded" } }))).toBe(false);
  });

  it("拖动、编辑、运行和失败不重置表单局部状态", () => {
    const draft = image({ form: { prompt: "原提示词" } });
    const key = itemFormResetKey(draft);
    expect(itemFormResetKey({ ...draft, x: 320, y: 180 })).toBe(key);
    expect(itemFormResetKey({ ...draft, form: { prompt: "正在输入的新提示词" } })).toBe(key);
    expect(itemFormResetKey({ ...draft, run: { status: "running", job_id: "job-1" } })).toBe(key);
    expect(itemFormResetKey({ ...draft, run: { status: "failed", error: "上游失败" } })).toBe(key);
  });

  it("AI 成功或手动换素材时从节点表单重新水合", () => {
    const running = image({ run: { status: "running", job_id: "job-1" } });
    const succeeded = image({ asset_id: "asset-1", run: { status: "succeeded" } });
    const replaced = image({ asset_id: "asset-2", run: { status: "idle" } });
    expect(itemFormResetKey(succeeded)).not.toBe(itemFormResetKey(running));
    expect(itemFormResetKey(replaced)).not.toBe(itemFormResetKey(succeeded));
  });
});

describe("终态轮询补丁", () => {
  it("成功时同步服务端清空后的表单，而不是只换 asset_id", () => {
    const item = image({
      asset_id: "asset-1",
      form: { prompt: "", provider: "evolink", model: "m", source_assets: [], mentioned_asset_ids: [] },
      run: { status: "succeeded" },
    });
    expect(boardSettlementPatch(item)).toMatchObject({ asset_id: "asset-1", form: item.form });
  });

  it("按状态认「跑完了」:没留下原因的失败、被取消,同样落回画布", () => {
    // 服务端不再拿状态名顶替原因 —— 原因可以没有,那一格照样要停下转圈。
    expect(boardSettlementPatch(image({ run: { status: "failed" } }))).toEqual({ run: { status: "failed" } });
    expect(boardSettlementPatch(image({ run: { status: "cancelled" } }))).toEqual({ run: { status: "cancelled" } });
  });

  it("便签写成了:补丁带回的是正文,不是 asset_id", () => {
    const note: BoardItem = { id: "n1", kind: "note", x: 0, y: 0, text: "写好的", form: { prompt: "" }, run: { status: "succeeded" } };
    expect(boardSettlementPatch(note)).toEqual({ text: "写好的", form: { prompt: "" }, run: { status: "succeeded" } });
  });

  it("还在跑的那一格不出补丁", () => {
    expect(boardSettlementPatch(image({ run: { status: "running", job_id: "job-1" } }))).toBeNull();
  });
});

describe("选中一格时挂哪块面板", () => {
  const trim = { asset_id: "src", start: 1, end: 3, mute: false };

  it("截挂了的那一格挂截取面板,不是生成/念的面板", () => {
    expect(producerOf({ id: "v", kind: "video", x: 0, y: 0, form: { trim, producer: "trim" }, run: { status: "failed", error: "截取失败" } })).toBe("trim");
    expect(producerOf({ id: "a", kind: "audio", x: 0, y: 0, form: { trim, producer: "trim" }, run: { status: "failed" } })).toBe("trim");
  });

  it("其余没有产出的照表单上写的:图片视频生成、音频念、便签写", () => {
    expect(producerOf(image({ form: { producer: "generate" }, run: { status: "failed", error: "上游失败" } }))).toBe("generate");
    expect(producerOf({ id: "a", kind: "audio", x: 0, y: 0, form: { producer: "speak" } })).toBe("speak");
    expect(producerOf({ id: "n", kind: "note", x: 0, y: 0, text: "有字", form: { producer: "write" } })).toBe("write");
  });

  it("有了产出的、分组框这类不挂", () => {
    expect(producerOf(image({ asset_id: "a1", form: { trim, producer: "trim" } }))).toBeNull();
    expect(producerOf({ id: "f", kind: "frame", x: 0, y: 0 })).toBeNull();
  });

  it("不按种类猜:表单上没写产出者就不挂", () => {
    expect(producerOf({ id: "a", kind: "audio", x: 0, y: 0 })).toBeNull();
    expect(producerOf({ id: "v", kind: "video", x: 0, y: 0, form: { trim } })).toBeNull();
  });

  it("新放下的一格写明产出者;带着产出或自带表单的不补", () => {
    expect(newSlotForm("note")).toEqual({ form: { producer: "write" } });
    expect(newSlotForm("image")).toEqual({ form: { producer: "generate" } });
    expect(newSlotForm("video")).toEqual({ form: { producer: "generate" } });
    expect(newSlotForm("audio")).toEqual({ form: { producer: "speak" } });
    expect(newSlotForm("frame")).toBeNull();
    expect(newSlotForm("image", { asset_id: "a1" })).toBeNull();
    expect(newSlotForm("video", { form: { trim, producer: "trim" } })).toBeNull();
  });

  it("别处新建的一格(3D 场景页的生成格)自带草稿、没写产出者:补上,草稿原样留着,产出者排最后", () => {
    const draft = { prompt: "镜头推进", source_assets: [{ asset_id: "f1", role: "first_frame" }] };
    const made = withSlotProducer({ id: "g", kind: "video", x: 0, y: 0, form: draft });
    expect(made.form).toEqual({ ...draft, producer: "generate" });
    expect(Object.keys(made.form ?? {}).at(-1)).toBe("producer");
    expect(producerOf(made)).toBe("generate");
    //: 写明了的不动;有了产出的媒体格、不产出的种类不补;便签有字照样补(它的产出是正文);3D 场景格挂渲白模,
    //: 有缩略图也补(缩略图不是它的产出,渲出来的落在右边)。
    expect(withSlotProducer(image({ form: { producer: "trim", trim } })).form?.producer).toBe("trim");
    expect(withSlotProducer(image({ asset_id: "a1" })).form).toBeUndefined();
    const scene: BoardItem = { id: "s", kind: "scene", x: 0, y: 0, scene_id: "s1", asset_id: "thumb" };
    const frame: BoardItem = { id: "f", kind: "frame", x: 0, y: 0 };
    const note: BoardItem = { id: "n", kind: "note", x: 0, y: 0, text: "有字" };
    expect(withSlotProducer(scene).form).toEqual({ producer: "scene_render" });
    expect(withSlotProducer(frame).form).toBeUndefined();
    expect(withSlotProducer(note).form).toEqual({ producer: "write" });
  });

  it("面板看不见产出者;存回来的表单把它补在最后", () => {
    const item = image({ form: { producer: "generate", prompt: "猫" } });
    expect(composerView(item).form).toEqual({ prompt: "猫" });
    expect(Object.keys(withProducer({ producer: "speak", prompt: "猫" }, "generate"))).toEqual(["prompt", "producer"]);
    expect(withProducer({ prompt: "猫" }, "generate")).toEqual({ prompt: "猫", producer: "generate" });
  });
});

describe("服务端摘掉的槽位素材,本地跟着摘", () => {
  const fed = { asset_id: "a1", role: "first_frame", from: "A" };
  const manual = { asset_id: "m1", role: "last_frame" };

  it("只摘服务端摘掉的那几份;请求在路上时又挂上的照留", () => {
    const sent = image({ form: { source_assets: [fed, manual] } });
    const stored = image({ form: { source_assets: [manual] } });
    const later = { asset_id: "r1", role: "reference_image" };
    const local = image({ form: { prompt: "又改了", source_assets: [fed, manual, later] } });
    expect(prunedLinksPatch(sent, stored, local)).toEqual({
      form: { prompt: "又改了", source_assets: [manual, later] },
    });
  });

  it("服务端什么都没摘就不出补丁", () => {
    const sent = image({ form: { source_assets: [fed, manual] } });
    expect(prunedLinksPatch(sent, sent, sent)).toBeNull();
  });
});
