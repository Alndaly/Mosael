import { describe, expect, it } from "vitest";
import {
  cameraOfShot,
  cameraPreset,
  hasObjectMotion,
  duplicateObject,
  initialScene,
  makeObject,
  makeShot,
  removeObjects,
  sampleCamera,
  sampleObject,
} from "./sceneGraph";
describe("editable scene graph", () => {
  it("does not remove a shot camera, including through its containing group", () => {
    const content = initialScene();
    const camera = cameraOfShot(content, content.shots[0])!;
    expect(removeObjects(content, [camera.id])).toBe(content);
    const group = makeObject("group");
    camera.parent_id = group.id;
    content.objects.push(group);
    expect(removeObjects(content, [group.id])).toBe(content);
    const spare = makeObject("camera");
    content.objects.push(spare);
    expect(removeObjects(content, [spare.id]).objects).not.toContain(spare);
  });
  it("samples every camera key exactly and holds at the bounds", () => {
    const content = initialScene(true);
    const shot = content.shots[0];
    const rig = cameraOfShot(content, shot)!;
    for (const f of rig.track)
      expect(sampleCamera(rig, shot, f.time)).toEqual({ ...f, time: f.time });
    expect(sampleCamera(rig, shot, -1)).toEqual({ ...rig.track[0], time: 0 });
    expect(sampleCamera(rig, shot, 100).position).toEqual(rig.track.at(-1)!.position);
  });

  it("a camera with no track just stays where it is", () => {
    // **空轨就是静止。** "有没有轨"正好等于"动不动" —— 一台不动的相机不该带一条只有一帧的轨。
    const { camera, shot } = makeShot();
    expect(camera.track).toEqual([]);
    for (const t of [0, 2.5, shot.duration])
      expect(sampleCamera(camera, shot, t)).toEqual({
        time: t,
        position: camera.position,
        target: camera.target,
        fov: camera.fov,
      });
  });

  it("interpolates camera position, target and field of view without changing the source track", () => {
    const { camera, shot } = makeShot();
    shot.easing = "linear";
    camera.track = [
      { time: 0, position: [0, 2, 10], target: [0, 1, 0], fov: 40 },
      { time: 5, position: [10, 4, 0], target: [0, 2, 0], fov: 60 },
    ];
    expect(sampleCamera(camera, shot, 2.5)).toEqual({
      time: 2.5,
      position: [5, 3, 5],
      target: [0, 1.5, 0],
      fov: 50,
    });
    expect(camera.track[0].fov).toBe(40);
  });

  it("a camera with a track is somewhere else at a later time —— 机位模型必须跟着走", () => {
    // 视口此前把相机排除在每帧重摆之外,于是机位模型一直停在静止姿态,而「俯瞰全场」里的
    // 取景器是按当前时刻算的 —— 同一台相机在画面上出现两个位置,看起来就是"机位错配"。
    // 这条钉的是"两个时刻确实不同",视口那边照着它摆。
    const content = initialScene(true);
    const shot = content.shots[0];
    const rig = cameraOfShot(content, shot)!;
    expect(rig.track.length).toBeGreaterThan(1);
    const start = sampleCamera(rig, shot, 0);
    const later = sampleCamera(rig, shot, shot.duration);
    expect(later.position).not.toEqual(start.position);
    // 静止姿态必须等于第一帧,否则没有轨的那一瞬间(比如刚加载)会先跳一下。
    expect(start.position).toEqual(rig.position);
    expect(start.target).toEqual(rig.target);
  });

  it("an object with no track just stays where it is", () => {
    const { shot } = makeShot();
    const box = makeObject("box", { position: [1, 2, 3], rotation: [0, 45, 0], scale: [2, 2, 2] });
    expect(box.track).toEqual([]);
    expect(sampleObject(box, shot, 2.5)).toEqual({
      position: [1, 2, 3],
      rotation: [0, 45, 0],
      scale: [2, 2, 2],
    });
  });

  it("walks an object between its keys, and keeps the fields a key does not mention", () => {
    // 关键帧只写一部分字段是常态:"只想让它平移"不该被迫把旋转和缩放也抄一遍。
    // 没写的沿用物体的静止值 —— 悄悄把它们归零的话,人会一边走一边缩成一个点。
    const { shot } = makeShot();
    shot.easing = "linear";
    const walker = makeObject("figure", { rotation: [0, 90, 0], scale: [1, 1, 1] });
    walker.track = [
      { time: 0, position: [0, 0, 0] },
      { time: 5, position: [10, 0, -4] },
    ];
    expect(sampleObject(walker, shot, 2.5)).toEqual({
      position: [5, 0, -2],
      rotation: [0, 90, 0],
      scale: [1, 1, 1],
    });
    expect(sampleObject(walker, shot, 99).position).toEqual([10, 0, -4]);
  });

  it("knows whether anything but the camera is moving", () => {
    // 视口据此决定要不要每帧重摆一次物体 —— 静态场景一帧也不该多算。
    const content = initialScene(true);
    expect(hasObjectMotion(content)).toBe(false);   // 示例场景只有相机在动
    const walker = makeObject("figure");
    walker.track = [{ time: 0, position: [0, 0, 0] }, { time: 3, position: [2, 0, 0] }];
    expect(hasObjectMotion({ ...content, objects: [...content.objects, walker] })).toBe(true);
  });

  it("duplicates nested groups with new identities and retains local transforms", () => {
    const c = initialScene();
    const group = makeObject("group"),
      child = makeObject("box", { parent_id: group.id, position: [2, 3, 4] });
    c.objects = [group, child];
    const d = duplicateObject(c, group.id);
    expect(d.objects).toHaveLength(4);
    expect(d.objects[3].parent_id).toBe(d.objects[2].id);
    expect(d.objects[3].position).toEqual([2, 3, 4]);
    expect(new Set(d.objects.map((o) => o.id)).size).toBe(4);
    expect(removeObjects(d, [group.id]).objects.map((o) => o.id)).toEqual(
      d.objects.slice(2).map((o) => o.id),
    );
  });
  it("orbit returns to the starting view and push maintains the target", () => {
    // 运镜现在长在相机上,所以 cameraPreset 返回的是**一条轨**,不是一个镜头。
    const { camera, shot } = makeShot();
    const orbit = cameraPreset(camera, shot, "orbit");
    expect(orbit).toHaveLength(9);
    expect(orbit.at(-1)!.position[0]).toBeCloseTo(camera.position[0]);
    expect(orbit.at(-1)!.time).toBe(shot.duration);
    expect(cameraPreset(camera, shot, "push")[1].target).toEqual(camera.target);
  });
});
