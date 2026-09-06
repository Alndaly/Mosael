import { describe, expect, it } from "vitest";
import {
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
    const s = initialScene(true).shots[0];
    for (const f of s.frames) expect(sampleCamera(s, f.time)).toEqual(f);
    expect(sampleCamera(s, -1)).toEqual(s.frames[0]);
    expect(sampleCamera(s, 100).position).toEqual(s.frames.at(-1)!.position);
  });
  it("interpolates camera position, target and field of view without changing source frames", () => {
    const s = makeShot();
    s.easing = "linear";
    s.frames = [
      { time: 0, position: [0, 2, 10], target: [0, 1, 0], fov: 40 },
      { time: 5, position: [10, 4, 0], target: [0, 2, 0], fov: 60 },
    ];
    expect(sampleCamera(s, 2.5)).toEqual({
      time: 2.5,
      position: [5, 3, 5],
      target: [0, 1.5, 0],
      fov: 50,
    });
    expect(s.frames[0].fov).toBe(40);
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
    const s = makeShot(),
      orbit = cameraPreset(s, "orbit");
    expect(orbit.frames).toHaveLength(9);
    expect(orbit.frames.at(-1)!.position[0]).toBeCloseTo(
      s.frames[0].position[0],
    );
    expect(orbit.frames.at(-1)!.time).toBe(s.duration);
    expect(cameraPreset(s, "push").frames[1].target).toEqual(
      s.frames[0].target,
    );
  });
});
