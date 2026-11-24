import { describe, expect, it } from "vitest";

import { azimuthFromPoint, DEFAULT_LIGHT, directionKey, elevationFromPoint, elevationHandle, lightPatch, matchingPreset, nudgeLight, orbPoint, readLight, LIGHT_PRESETS } from "./lightRig";

describe("打光节点的灯位(ADR 0108)", () => {
  it("读配置:没写的用缺省(和后端同一份),超出的夹住,方位按圈取余", () => {
    expect(readLight({})).toEqual(DEFAULT_LIGHT);
    expect(readLight({ light_azimuth: -90, light_elevation: 120, light_temperature: 100, light_softness: "0.3", light_intensity: "" }))
      .toEqual({ azimuth: 270, elevation: 90, temperature: 1500, softness: 0.3, intensity: DEFAULT_LIGHT.intensity });
  });

  it("写回只写改了的那几格,键名和后端节点同名", () => {
    expect(lightPatch({ azimuth: 90.123, softness: 0.5 })).toEqual({ light_azimuth: 90.12, light_softness: 0.5 });
  });

  it("方向球:顺光在人前面、偏下;逆光在后面;右侧光在右边;顶光在正上方", () => {
    const front = orbPoint(0, 0);
    expect(front.front).toBe(true);
    expect(front.y).toBeGreaterThan(0);
    expect(orbPoint(180, 0).front).toBe(false);
    expect(orbPoint(90, 0).x).toBeCloseTo(1);
    expect(orbPoint(0, 90).x).toBeCloseTo(0);
    expect(orbPoint(0, 90).y).toBeLessThan(-0.9);
  });

  it("方向键微调:方位绕圈,高度夹在 0–90", () => {
    expect(nudgeLight({ azimuth: 350, elevation: 45 }, 20, 10)).toEqual({ azimuth: 10, elevation: 55 });
    expect(nudgeLight({ azimuth: 0, elevation: 88 }, 0, 5).elevation).toBe(90);
  });

  it("方位把手:指针落在环上哪里,方位就是哪里(和光点在环上的位置互逆)", () => {
    for (const azimuth of [0, 45, 90, 180, 270, 315]) {
      const point = orbPoint(azimuth, 0);
      expect(azimuthFromPoint(point.x, point.y)).toBeCloseTo(azimuth, 5);
    }
    //: 指针在环外,照方向算:正右边就是 90°。
    expect(azimuthFromPoint(3, 0)).toBeCloseTo(90);
  });

  it("高度把手:左边地平线是 0、正上方是 90,和把手的位置互逆;越界的夹住", () => {
    for (const elevation of [0, 30, 60, 90]) {
      const point = elevationHandle(elevation);
      expect(elevationFromPoint(point.x, point.y)).toBeCloseTo(elevation, 5);
    }
    expect(elevationFromPoint(-1, 0.5)).toBe(0);
    expect(elevationFromPoint(1, -1)).toBe(90);
  });

  it("八个方向和后端翻指令时的分法一样:359° 是正面,不是左前方", () => {
    expect(directionKey(359)).toBe("lightDirFront");
    expect(directionKey(268)).toBe("lightDirLeft");
    expect(directionKey(180)).toBe("lightDirBack");
  });

  it("现在这一套正好是哪个预设;拖动之后就不是了", () => {
    const rembrandt = LIGHT_PRESETS[0];
    expect(matchingPreset(rembrandt.light)).toBe(rembrandt.id);
    expect(matchingPreset({ ...rembrandt.light, azimuth: 300 })).toBeNull();
  });
});
