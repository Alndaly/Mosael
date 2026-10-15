/** @vitest-environment jsdom */
/**
 * 快照渲染路径(WebGLRenderer → toBlob)在 jsdom 里跑不起真 GL —— mock 渲染器,
 * 钉的是**编排本身**:按尺寸 setSize、渲了一次、toBlob 拿到非空 PNG、渲染器 dispose、
 * 传进来的活人偶根没被离屏场景抢走(内部克隆 protective)。
 */
import { describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  renders: 0,
  sizes: [] as Array<[number, number]>,
  disposed: 0,
}));

vi.mock("three", async (importOriginal) => {
  const actual = await importOriginal<typeof import("three")>();
  class MockWebGLRenderer {
    domElement = {
      toBlob: (callback: (blob: Blob | null) => void) =>
        callback(new Blob(["mock-png-bytes"], { type: "image/png" })),
    };
    shadowMap = { enabled: false, type: "" };
    outputColorSpace = "";
    toneMapping = 0;
    setPixelRatio() {}
    setSize(width: number, height: number) {
      mocks.sizes.push([width, height]);
    }
    render() {
      mocks.renders += 1;
    }
    dispose() {
      mocks.disposed += 1;
    }
  }
  return { ...actual, WebGLRenderer: MockWebGLRenderer };
});

import { applyPose, createMannequin } from "./mannequinRig";
import { MANNEQUIN_POSES } from "./mannequinPoses";
import {
  MANNEQUIN_SNAPSHOT_SIZES,
  renderMannequinSnapshot,
} from "./mannequinSnapshot";

describe("renderMannequinSnapshot(离屏渲染编排)", () => {
  it("方形 1024²:渲一次,产出非空 PNG,渲染器 dispose", async () => {
    mocks.renders = 0;
    mocks.disposed = 0;
    const rig = createMannequin();
    const blob = await renderMannequinSnapshot(rig.root, "square");
    expect(mocks.renders).toBe(1);
    expect(mocks.disposed).toBe(1);
    expect(mocks.sizes.at(-1)).toEqual([
      MANNEQUIN_SNAPSHOT_SIZES.square.width,
      MANNEQUIN_SNAPSHOT_SIZES.square.height,
    ]);
    expect(blob.type).toBe("image/png");
    expect(blob.size).toBeGreaterThan(0);
  });

  it("竖图 768×1024:尺寸跟着档位走", async () => {
    const rig = createMannequin();
    applyPose(rig, MANNEQUIN_POSES.armsUp!);
    const blob = await renderMannequinSnapshot(rig.root, "portrait");
    expect(mocks.sizes.at(-1)).toEqual([768, 1024]);
    expect(blob.size).toBeGreaterThan(0);
  });

  it("人偶根仍挂在原处 —— 离屏场景拿的是克隆", async () => {
    const rig = createMannequin();
    await renderMannequinSnapshot(rig.root, "square");
    expect(rig.root.parent).toBeNull();
    expect(rig.root.children.length).toBeGreaterThan(0);
  });
});
