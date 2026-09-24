import { expect, it } from "vitest";
import { Group, Mesh, BoxGeometry, MeshBasicMaterial } from "three";
import { PointLight } from "three";
import { cloneSceneForExport, visibleBounds } from "./sceneExport";

it("omits nested camera helpers without changing the live scene or geometry", () => {
  const root = new Group();
  const group = new Group();
  group.position.set(2, 3, 4);
  const camera = new Group();
  camera.userData.editorOnly = true;
  const mesh = new Mesh(new BoxGeometry(), new MeshBasicMaterial());
  group.add(camera, mesh);
  root.add(group);
  const copy = cloneSceneForExport(root);
  expect(copy.children[0].children).toHaveLength(1);
  expect((copy.children[0].children[0] as Mesh).geometry).toBe(mesh.geometry);
  expect(copy.children[0].position.toArray()).toEqual([2, 3, 4]);
  expect(group.children).toEqual([camera, mesh]);
});

/**
 * 藏起来的物体不进出片:参考帧、参考视频和 GLB 都从 cloneSceneForExport 拿场景。
 * 此前靠渲染器和 GLTFExporter 各自"跳过不可见"的默认值碰巧一致,而藏起来的灯仍留在导出场景里。
 */
it("drops hidden objects and everything under a hidden group, without touching the live scene", () => {
  const root = new Group();
  const shown = new Mesh(new BoxGeometry(), new MeshBasicMaterial());
  const hiddenLamp = new Group();
  hiddenLamp.visible = false;
  hiddenLamp.add(new PointLight());
  const hiddenGroup = new Group();
  hiddenGroup.visible = false;
  const child = new Mesh(new BoxGeometry(), new MeshBasicMaterial());
  hiddenGroup.add(child);
  root.add(shown, hiddenLamp, hiddenGroup);

  const copy = cloneSceneForExport(root);
  expect(copy.children).toHaveLength(1);
  let lights = 0;
  copy.traverse((node) => {
    if (node instanceof PointLight) lights++;
  });
  expect(lights).toBe(0);
  expect(root.children).toEqual([shown, hiddenLamp, hiddenGroup]);
});

it("frames only what is visible — a hidden floor must not widen the shadow box or the overview", () => {
  const root = new Group();
  const prop = new Mesh(new BoxGeometry(1, 1, 1), new MeshBasicMaterial());
  const group = new Group();
  group.visible = false;
  const floor = new Mesh(new BoxGeometry(100, 0.1, 100), new MeshBasicMaterial());
  group.add(floor);
  root.add(prop, group);
  const bounds = visibleBounds(root);
  expect(bounds.max.x).toBeCloseTo(0.5);
  expect(bounds.min.z).toBeCloseTo(-0.5);
  group.visible = true;
  expect(visibleBounds(root).max.x).toBeCloseTo(50);
});
