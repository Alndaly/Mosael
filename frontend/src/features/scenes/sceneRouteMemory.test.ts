import { expect, it } from "vitest";
import { SceneRouteMemory } from "./sceneRouteMemory";
it("restores detail across other tabs but respects explicitly returning to the list", () => {
  const routes = new SceneRouteMemory();
  routes.visit("a", "#/scenes?scene=one");
  routes.visit("a", "#/notes?note=two");
  expect(routes.restore("a")).toBe("#/scenes?scene=one");
  routes.visit("a", "#/scenes");
  expect(routes.restore("a")).toBe("#/scenes");
});
it("isolates workspaces and does not treat similarly named paths as scenes", () => {
  const routes = new SceneRouteMemory();
  routes.visit("a", "#/scenes?scene=one");
  routes.visit("a", "#/scenes-other?scene=two");
  expect(routes.restore("b")).toBe("#/scenes");
  routes.visit("b", "#/scenes?scene=three");
  expect(routes.restore("a")).toBe("#/scenes?scene=one");
});
