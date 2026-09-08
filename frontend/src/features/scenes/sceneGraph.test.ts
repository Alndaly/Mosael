import { describe, expect, it } from "vitest";
import {
  cameraOfShot,
  cameraPreset,
  duplicateObject,
  initialScene,
  makeObject,
  makeShot,
  removeObjects,
  sampleCamera,
} from "./sceneGraph";
describe("editable scene graph", () => {
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
