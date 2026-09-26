/** @vitest-environment jsdom */
/**
 * 「3D 页面每次进入视角都会重新恢复到默认视角」。
 *
 * 视角是**这个人**的编辑器状态:存本地、按场景分开、坏数据当没存过。视口本身跑不了 WebGL,
 * 这里在控制器那一层验 —— 真的 three 相机 + 真的 OrbitControls,和视口里接的是同一套。
 */
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { PerspectiveCamera } from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";

import {
  DEFAULT_SCENE_VIEW,
  SCENE_VIEW_LIMIT,
  applyOrbit,
  captureOrbit,
  forgetSceneView,
  parseSceneView,
  readSceneView,
  rememberedShot,
  sceneViewKey,
  throttledSave,
  writeSceneView,
  type OrbitView,
} from "./sceneViewMemory";

const behind: OrbitView = { position: [-6, 3, -9], target: [1, 0.5, 2], fov: 35 };

beforeEach(() => localStorage.clear());
afterEach(() => vi.useRealTimers());

describe("按场景记住视角", () => {
  it("没存过就是默认 —— 视口照旧用自己的默认机位", () => {
    expect(readSceneView("w1", "s1")).toEqual(DEFAULT_SCENE_VIEW);
  });

  it("存了再读回来是同一个;视角档和相机分两次写,互不抹掉", () => {
    writeSceneView("w1", "s1", { mode: "observe", shotId: "shot-2" });
    writeSceneView("w1", "s1", {
      free: behind,
      overview: { position: [0, 30, 20], target: [0, 0, 0], fov: 45, shotId: "shot-2" },
    });
    expect(readSceneView("w1", "s1")).toEqual({
      mode: "observe",
      shotId: "shot-2",
      free: behind,
      overview: { position: [0, 30, 20], target: [0, 0, 0], fov: 45, shotId: "shot-2" },
    });
    // undefined 的字段 = 不动它,而不是清掉。
    writeSceneView("w1", "s1", { free: { ...behind, fov: 50 }, overview: undefined });
    expect(readSceneView("w1", "s1").overview?.shotId).toBe("shot-2");
    expect(localStorage.getItem("mosael:scene-view:w1:s1")).not.toBeNull();
  });

  it("每个场景各是各的,换工作区也不串", () => {
    writeSceneView("w1", "s1", { mode: "camera", free: behind });
    expect(readSceneView("w1", "s2")).toEqual(DEFAULT_SCENE_VIEW);
    expect(readSceneView("w2", "s1")).toEqual(DEFAULT_SCENE_VIEW);
    writeSceneView("w1", "s2", { mode: "observe" });
    expect(readSceneView("w1", "s1").mode).toBe("camera");
    expect(readSceneView("w1", "s1").free).toEqual(behind);
  });

  it.each([
    ["不是 JSON", "{oops"],
    ["是数组", "[1,2,3]"],
    ["是 null", "null"],
  ])("整条坏了(%s)→ 当没存过", (_, raw) => {
    localStorage.setItem(sceneViewKey("w1", "s1"), raw);
    expect(parseSceneView(raw)).toBeNull();
    expect(readSceneView("w1", "s1")).toEqual(DEFAULT_SCENE_VIEW);
  });

  it.each([
    ["坐标不是数", { position: ["6", 3, 9], target: [0, 0, 0], fov: 45 }],
    ["坐标是 null(JSON 里的 NaN / Infinity)", { position: [null, 3, 9], target: [0, 0, 0], fov: 45 }],
    ["少一个分量", { position: [6, 3], target: [0, 0, 0], fov: 45 }],
    ["大得离谱", { position: [1e300, 3, 9], target: [0, 0, 0], fov: 45 }],
    ["相机和目标重合", { position: [1, 1, 1], target: [1, 1, 1], fov: 45 }],
    ["视场为 0", { position: [6, 3, 9], target: [0, 0, 0], fov: 0 }],
    ["视场过大", { position: [6, 3, 9], target: [0, 0, 0], fov: 400 }],
    ["没有视场", { position: [6, 3, 9], target: [0, 0, 0] }],
  ])("相机那段坏了(%s)→ 只有那段回默认,视角档照用", (_, free) => {
    localStorage.setItem(sceneViewKey("w1", "s1"), JSON.stringify({ mode: "camera", shotId: "a", free }));
    expect(readSceneView("w1", "s1")).toEqual({ ...DEFAULT_SCENE_VIEW, mode: "camera", shotId: "a" });
  });

  it("不认识的视角档、空镜头 id、没说框的是哪个镜头的俯瞰 → 各自回默认", () => {
    localStorage.setItem(
      sceneViewKey("w1", "s1"),
      JSON.stringify({ mode: "timeline", shotId: "", free: behind, overview: { ...behind } }),
    );
    expect(readSceneView("w1", "s1")).toEqual({ ...DEFAULT_SCENE_VIEW, free: behind });
  });

  it("没有 storage(隐私模式)也不抛:读回默认,写就当没写", () => {
    const get = vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new Error("SecurityError");
    });
    const set = vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new Error("QuotaExceededError");
    });
    try {
      expect(readSceneView("w1", "s1")).toEqual(DEFAULT_SCENE_VIEW);
      expect(() => writeSceneView("w1", "s1", { mode: "camera" })).not.toThrow();
      expect(() => forgetSceneView("w1", "s1")).not.toThrow();
    } finally {
      get.mockRestore();
      set.mockRestore();
    }
  });

  it(`只留最近 ${SCENE_VIEW_LIMIT} 个场景,最久没碰的先被挤掉`, () => {
    for (let i = 0; i <= SCENE_VIEW_LIMIT; i++) writeSceneView("w1", `s${i}`, { mode: "camera" });
    expect(localStorage.getItem(sceneViewKey("w1", "s0"))).toBeNull();
    expect(readSceneView("w1", "s1").mode).toBe("camera");
    expect(readSceneView("w1", `s${SCENE_VIEW_LIMIT}`).mode).toBe("camera");
    // 再碰一下 s1,它就回到最前面;下一个被挤掉的是 s2。
    writeSceneView("w1", "s1", { mode: "observe" });
    writeSceneView("w1", "fresh", { mode: "camera" });
    expect(readSceneView("w1", "s1").mode).toBe("observe");
    expect(localStorage.getItem(sceneViewKey("w1", "s2"))).toBeNull();
  });

  it("删掉场景时一并忘掉它的视角", () => {
    writeSceneView("w1", "s1", { mode: "camera", free: behind });
    writeSceneView("w1", "s2", { mode: "observe" });
    forgetSceneView("w1", "s1");
    expect(localStorage.getItem(sceneViewKey("w1", "s1"))).toBeNull();
    expect(readSceneView("w1", "s2").mode).toBe("observe");
    expect(JSON.parse(localStorage.getItem("mosael:scene-view-recent")!)).toEqual([sceneViewKey("w1", "s2")]);
  });

  it("存着的镜头被删了就回到第一个", () => {
    const shots = [{ id: "a" }, { id: "b" }];
    expect(rememberedShot({ ...DEFAULT_SCENE_VIEW, shotId: "b" }, shots)).toBe("b");
    expect(rememberedShot({ ...DEFAULT_SCENE_VIEW, shotId: "gone" }, shots)).toBe("a");
    expect(rememberedShot(DEFAULT_SCENE_VIEW, shots)).toBe("a");
  });
});

describe("相机在动时节流存盘", () => {
  it("一串变化最多每 300ms 写一次,flush 立刻落下挂着的那次", () => {
    vi.useFakeTimers();
    const save = vi.fn();
    const saver = throttledSave(save, 300);
    for (let i = 0; i < 20; i++) saver.schedule();
    expect(save).not.toHaveBeenCalled();
    vi.advanceTimersByTime(300);
    expect(save).toHaveBeenCalledTimes(1);
    saver.schedule();
    saver.flush();
    expect(save).toHaveBeenCalledTimes(2);
    vi.advanceTimersByTime(1000);
    expect(save).toHaveBeenCalledTimes(2);
    saver.flush(); // 没有挂着的就什么也不做
    expect(save).toHaveBeenCalledTimes(2);
  });
});

/** 和视口里一样的编辑相机:同样的默认机位、同样的轨道控制。 */
function editor() {
  const canvas = document.createElement("div");
  document.body.append(canvas);
  const camera = new PerspectiveCamera(45, 16 / 9, 0.05, 2000);
  camera.position.set(12, 10, 14);
  const orbit = new OrbitControls(camera, canvas);
  orbit.target.set(0, 1, -3);
  orbit.enableDamping = true;
  orbit.minDistance = 0.1;
  orbit.maxDistance = 1000;
  return {
    camera,
    orbit,
    dispose: () => {
      orbit.dispose();
      canvas.remove();
    },
  };
}

const close = (actual: number[], expected: number[]) =>
  actual.forEach((n, i) => expect(n).toBeCloseTo(expected[i], 6));

describe("视口按存着的视角摆相机,而不是默认机位", () => {
  it("摆回来就是那个视角,轨道控制跑一帧也不漂", () => {
    const { camera, orbit, dispose } = editor();
    try {
      applyOrbit(camera, orbit, behind);
      orbit.update(); // 渲染循环每帧都会调
      const now = captureOrbit(camera, orbit);
      close(now.position, behind.position);
      close(now.target, behind.target);
      expect(now.fov).toBe(35);
      expect(camera.projectionMatrix.elements.every(Number.isFinite)).toBe(true);
    } finally {
      dispose();
    }
  });

  it("拉得很远的视角回来时远裁剪面跟着放宽", () => {
    const { camera, orbit, dispose } = editor();
    try {
      applyOrbit(camera, orbit, { position: [0, 0, 500], target: [0, 0, 0], fov: 45 });
      expect(camera.far).toBe(5000);
    } finally {
      dispose();
    }
  });

  it("按钮重置之后,记住的是重置后的样子(走和视口同一条 change → 节流 → 写入)", () => {
    vi.useFakeTimers();
    const { camera, orbit, dispose } = editor();
    try {
      const saver = throttledSave(() => writeSceneView("w1", "s1", { free: captureOrbit(camera, orbit) }));
      orbit.addEventListener("change", () => saver.schedule());
      applyOrbit(camera, orbit, behind);
      // 「聚焦」/「顶视」这类按钮:直接改相机和目标,下一帧 update 发 change。
      orbit.target.set(0, 0, 0);
      camera.position.set(0, 20, 0.02);
      orbit.update();
      vi.advanceTimersByTime(300);
      const stored = readSceneView("w1", "s1").free!;
      close(stored.target, [0, 0, 0]);
      close(stored.position, [0, 20, 0.02]);

      // 下次进来:一个全新的视口按它摆,而不是停在 (12, 10, 14)。
      const next = editor();
      try {
        applyOrbit(next.camera, next.orbit, readSceneView("w1", "s1").free!);
        close(captureOrbit(next.camera, next.orbit).position, [0, 20, 0.02]);
      } finally {
        next.dispose();
      }
    } finally {
      dispose();
    }
  });
});
