import { expect, it } from "vitest";
import { Group, Mesh, BoxGeometry, MeshBasicMaterial } from "three";
import { cloneSceneForExport } from "./sceneExport";

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
