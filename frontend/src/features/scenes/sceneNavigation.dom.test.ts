/** @vitest-environment jsdom */
import { afterEach, expect, it } from "vitest";
import { PerspectiveCamera } from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import {
  attachSceneNavigation,
  type SceneNavigationMode,
} from "./sceneNavigation";
const dispose: (() => void)[] = [];
afterEach(() => {
  dispose.splice(0).forEach((f) => f());
});
function setup() {
  const canvas = document.createElement("div");
  Object.defineProperties(canvas, {
    clientWidth: { value: 800 },
    clientHeight: { value: 600 },
  });
  document.body.append(canvas);
  const camera = new PerspectiveCamera(45, 4 / 3, 0.05, 2000);
  camera.position.set(12, 10, 14);
  const orbit = new OrbitControls(camera, canvas);
  orbit.target.set(0, 1, -3);
  orbit.update();
  orbit.enableDamping = true;
  orbit.minDistance = 0.1;
  orbit.maxDistance = 1000;
  const state = { mode: "trackpad" as SceneNavigationMode, disabled: false };
  const remove = attachSceneNavigation(canvas, orbit, () => state);
  dispose.push(() => {
    remove();
    orbit.dispose();
    canvas.remove();
  });
  const wheel = (values: WheelEventInit) => {
    const event = new WheelEvent("wheel", {
      bubbles: true,
      cancelable: true,
      ...values,
    });
    canvas.dispatchEvent(event);
    return event;
  };
  const gesture = (type: string, scale = 1) => {
    const event = new Event(type, { bubbles: true, cancelable: true });
    Object.defineProperty(event, "scale", { value: scale });
    canvas.dispatchEvent(event);
  };
  return { canvas, camera, orbit, state, wheel, gesture, remove };
}
it("pans both axes without changing distance, then pinches without moving the target", () => {
  const { camera, orbit, wheel } = setup();
  const offset = camera.position.clone().sub(orbit.target);
  const target = orbit.target.clone();
  expect(wheel({ deltaX: 24.5, deltaY: 38.2 }).defaultPrevented).toBe(true);
  expect(orbit.target.distanceTo(target)).toBeGreaterThan(0.1);
  expect(
    camera.position.clone().sub(orbit.target).distanceTo(offset),
  ).toBeLessThan(1e-8);
  const nextTarget = orbit.target.clone(),
    distance = offset.length();
  wheel({ deltaY: -12, ctrlKey: true });
  expect(camera.position.distanceTo(orbit.target)).toBeCloseTo(
    distance * Math.exp(-0.12),
  );
  expect(orbit.target.distanceTo(nextTarget)).toBeLessThan(1e-8);
  expect(orbit.enableDamping).toBe(true);
});
it("orbits around a fixed target with Shift and normalizes line delta units", () => {
  const a = setup(),
    b = setup();
  const target = a.orbit.target.clone();
  const offset = a.camera.position.clone().sub(target);
  a.wheel({ shiftKey: true, deltaX: 32, deltaY: 16 });
  b.wheel({ shiftKey: true, deltaX: 2, deltaY: 1, deltaMode: 1 });
  expect(a.camera.position.distanceTo(b.camera.position)).toBeLessThan(1e-8);
  expect(a.orbit.target.distanceTo(target)).toBeLessThan(1e-8);
  expect(a.camera.position.distanceTo(target)).toBeCloseTo(offset.length());
  expect(
    a.camera.position.clone().sub(target).distanceTo(offset),
  ).toBeGreaterThan(1);
});
it("keeps previews and object dragging read-only without letting wheel events reach the page", () => {
  const { canvas, camera, state, wheel, gesture } = setup();
  state.disabled = true;
  const before = camera.position.clone();
  let bubbled = false;
  const listener = () => {
    bubbled = true;
  };
  document.body.addEventListener("wheel", listener);
  try {
    expect(wheel({ ctrlKey: true, deltaY: -40 }).defaultPrevented).toBe(true);
  } finally {
    document.body.removeEventListener("wheel", listener);
  }
  gesture("gesturestart");
  gesture("gesturechange", 1.4);
  gesture("gestureend");
  expect(bubbled).toBe(false);
  expect(camera.position.equals(before)).toBe(true);
  expect(canvas.isConnected).toBe(true);
});
it("handles WebKit scale increments once and suppresses duplicate wheel pinches", () => {
  const { camera, orbit, gesture, wheel } = setup();
  const distance = camera.position.distanceTo(orbit.target);
  gesture("gesturestart");
  gesture("gesturechange", 1.2);
  wheel({ deltaY: -20, ctrlKey: true });
  gesture("gesturechange", 1.5);
  gesture("gestureend");
  expect(camera.position.distanceTo(orbit.target)).toBeCloseTo(distance / 1.5);
});
it("preserves mouse wheel zoom and removes its own listeners on teardown", () => {
  const { camera, orbit, state, wheel, remove } = setup();
  state.mode = "mouse";
  const target = orbit.target.clone(),
    distance = camera.position.distanceTo(target);
  wheel({ deltaY: 100 });
  expect(camera.position.distanceTo(target)).toBeGreaterThan(distance);
  expect(orbit.target.equals(target)).toBe(true);
  remove();
  orbit.dispose();
  const before = camera.position.clone();
  expect(wheel({ deltaY: 40 }).defaultPrevented).toBe(false);
  expect(camera.position.equals(before)).toBe(true);
});
it("bounds extreme pinch input and keeps the camera finite", () => {
  const { camera, orbit, wheel } = setup();
  for (let i = 0; i < 30; i++) wheel({ ctrlKey: true, deltaY: -10000 });
  expect(camera.position.distanceTo(orbit.target)).toBeCloseTo(0.1);
  for (let i = 0; i < 30; i++) wheel({ ctrlKey: true, deltaY: 10000 });
  expect(camera.position.distanceTo(orbit.target)).toBeCloseTo(1000);
  expect(camera.position.toArray().every(Number.isFinite)).toBe(true);
});

it("routes trackpad input to the active observation camera without moving the edit camera", () => {
  const { canvas, camera, orbit, wheel, remove, state } = setup();
  remove();
  const observerCamera = camera.clone();
  const observerOrbit = new OrbitControls(observerCamera, canvas);
  observerOrbit.target.copy(orbit.target);
  observerOrbit.update();
  let observing = true;
  orbit.enabled = false;
  const cleanup = attachSceneNavigation(
    canvas,
    () => (observing ? observerOrbit : orbit),
    () => state,
  );
  const original = camera.position.clone();
  const before = observerCamera.position.clone();
  wheel({ deltaX: 30, deltaY: 40 });
  expect(observerCamera.position.distanceTo(before)).toBeGreaterThan(0.1);
  expect(camera.position.equals(original)).toBe(true);
  const observed = observerCamera.position.clone();
  observing = false;
  orbit.enabled = true;
  observerOrbit.enabled = false;
  wheel({ deltaY: -30, ctrlKey: true });
  expect(observerCamera.position.equals(observed)).toBe(true);
  expect(camera.position.distanceTo(original)).toBeGreaterThan(0.1);
  cleanup();
  observerOrbit.dispose();
});
