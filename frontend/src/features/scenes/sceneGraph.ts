import { presetById } from "./lighting";
import type {
  CameraFrame,
  SceneContent,
  SceneObject,
  SceneShot,
  Vec3,
} from "@/api/domains/scenes";
export const objectLabels: Record<SceneObject["kind"], string> = {
  box: "立方体",
  sphere: "球体",
  cylinder: "圆柱",
  plane: "地面",
  room: "房间",
  stairs: "楼梯",
  group: "组",
  model: "模型",
  light: "灯光",
};
export const uid = () => crypto.randomUUID();
export function makeObject(
  kind: SceneObject["kind"],
  patch: Partial<SceneObject> = {},
): SceneObject {
  return {
    id: uid(),
    name: objectLabels[kind],
    kind,
    parent_id: null,
    position: [0, kind === "light" ? 4 : 0, 0],
    rotation: [0, 0, 0],
    scale: [1, 1, 1],
    parameters: {
      width: 2,
      height: 2,
      depth: 2,
      radius: 1,
      steps: 8,
      door_width: 1.6,
      door_height: 2.5,
    },
    color: "#c4b8a6",
    roughness: 0.6,
    metalness: 0,
    intensity: 40,
    hidden: false,
    model_id: null,
    ...patch,
  };
}
export function makeShot(): SceneShot {
  return {
    id: uid(),
    name: "镜头 1",
    duration: 5,
    aspect: "16:9",
    easing: "smooth",
    frames: [{ time: 0, position: [8, 5, 8], target: [0, 1, 0], fov: 45 }],
  };
}
/** 新场景的默认打光。**和后端 SceneLighting 的默认值同一档**(studio-soft) —— 两边写不一样的
 *  话,新建出来的场景和"重置为默认"会落在不同的光下,而没有任何地方会报错。 */
const DEFAULT_LIGHTING = { preset: "studio-soft", ...presetById("studio-soft")!.values };

export function initialScene(demo = false): SceneContent {
  const shot = makeShot();
  if (!demo)
    return {
      version: 1,
      lighting: DEFAULT_LIGHTING,
      objects: [
        makeObject("plane", {
          name: "地面",
          parameters: {
            ...makeObject("plane").parameters,
            width: 20,
            depth: 20,
          },
          color: "#454b51",
        }),
      ],
      shots: [shot],
      background: "#20242c",
      ambient: 1.5,
    };
  const rooms = [0, 1, 2].map((i) =>
    makeObject("room", {
      name: `展厅 ${i + 1}`,
      position: [0, 0, -i * 6.15],
      parameters: {
        ...makeObject("room").parameters,
        width: 6,
        height: 3.5,
        depth: 6,
      },
      color: ["#c5b6a1", "#aebdc0", "#beb1c6"][i],
    }),
  );
  shot.name = "穿过三间展厅";
  shot.duration = 10;
  shot.frames = [
    { time: 0, position: [0, 1.6, 5], target: [0, 1.6, -1], fov: 55 },
    { time: 3, position: [0, 1.6, -2], target: [0, 1.6, -8], fov: 55 },
    { time: 6, position: [0, 1.6, -8], target: [0, 1.4, -12], fov: 50 },
    { time: 8, position: [2, 2, -12], target: [0, 1, -12], fov: 50 },
    { time: 10, position: [0, 2, -14], target: [0, 1, -12], fov: 50 },
  ];
  return {
    version: 1,
    lighting: DEFAULT_LIGHTING,
    objects: [
      ...rooms,
      makeObject("cylinder", {
        name: "展台",
        position: [0, 0, -12],
        parameters: { ...makeObject("cylinder").parameters, height: 0.6 },
        color: "#565e67",
      }),
      makeObject("sphere", {
        name: "产品占位球",
        position: [0, 0.6, -12],
        parameters: { ...makeObject("sphere").parameters, radius: 0.6 },
        color: "#d6a55b",
        metalness: 0.7,
        roughness: 0.2,
      }),
    ],
    shots: [shot],
    background: "#20242c",
    ambient: 1.8,
  };
}
export function sampleCamera(shot: SceneShot, time: number): CameraFrame {
  const frames = shot.frames;
  const t = Math.max(0, Math.min(time, shot.duration));
  const next = frames.findIndex((f) => f.time > t);
  if (next < 0) return { ...frames[frames.length - 1], time: t };
  if (next === 0) return { ...frames[0], time: t };
  const a = frames[next - 1],
    b = frames[next];
  let u = (t - a.time) / (b.time - a.time);
  if (shot.easing === "smooth") u = u * u * (3 - 2 * u);
  const mix = (a: Vec3, b: Vec3) => a.map((v, i) => v + (b[i] - v) * u) as Vec3;
  return {
    time: t,
    position: mix(a.position, b.position),
    target: mix(a.target, b.target),
    fov: a.fov + (b.fov - a.fov) * u,
  };
}
export function removeObjects(
  content: SceneContent,
  ids: string[],
): SceneContent {
  const removed = new Set(ids);
  let changed = true;
  while (changed) {
    changed = false;
    for (const o of content.objects)
      if (o.parent_id && removed.has(o.parent_id) && !removed.has(o.id)) {
        removed.add(o.id);
        changed = true;
      }
  }
  return {
    ...content,
    objects: content.objects.filter((o) => !removed.has(o.id)),
  };
}
export function duplicateObject(
  content: SceneContent,
  id: string,
): SceneContent {
  const root = content.objects.find((o) => o.id === id);
  if (!root) return content;
  const descendants = new Set([id]);
  let changed = true;
  while (changed) {
    changed = false;
    for (const o of content.objects)
      if (
        o.parent_id &&
        descendants.has(o.parent_id) &&
        !descendants.has(o.id)
      ) {
        descendants.add(o.id);
        changed = true;
      }
  }
  const map = new Map([...descendants].map((id) => [id, uid()]));
  const copies = content.objects
    .filter((o) => descendants.has(o.id))
    .map((o) => ({
      ...structuredClone(o),
      id: map.get(o.id)!,
      parent_id: o.parent_id ? (map.get(o.parent_id) ?? o.parent_id) : null,
      name: o.id === id ? `${o.name} 副本` : o.name,
      position:
        o.id === id
          ? ([o.position[0] + 1, ...o.position.slice(1)] as Vec3)
          : o.position,
    }));
  return { ...content, objects: [...content.objects, ...copies] };
}
export function cameraPreset(
  shot: SceneShot,
  kind: "orbit" | "push",
): SceneShot {
  const first = shot.frames[0],
    target = first.target;
  if (kind === "push")
    return {
      ...shot,
      frames: [
        first,
        {
          ...first,
          time: shot.duration,
          position: first.position.map(
            (v, i) => v + (target[i] - v) * 0.5,
          ) as Vec3,
        },
      ],
    };
  const dx = first.position[0] - target[0],
    dz = first.position[2] - target[2];
  return {
    ...shot,
    frames: Array.from({ length: 9 }, (_, i) => {
      const a = (i / 8) * Math.PI * 2;
      return {
        ...first,
        time: (shot.duration * i) / 8,
        position: [
          target[0] + dx * Math.cos(a) - dz * Math.sin(a),
          first.position[1],
          target[2] + dx * Math.sin(a) + dz * Math.cos(a),
        ] as Vec3,
      };
    }),
  };
}
