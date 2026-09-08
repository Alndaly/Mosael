import { presetById } from "./lighting";
import type {
  Keyframe,
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
  camera: "机位",
  figure: "人物",
  table: "桌子",
};

/** 每一类新建时的尺寸。**只写和默认值不同的那几个** —— 其余走 makeObject 里那份。
 *
 *  人物默认 1.7 米:这一页最常见的用途是**看构图和比例** —— 相机是不是在视平线上、
 *  门有多高、桌子够不够到手,都靠一个真人尺寸的参照才判断得出来。给个 2 米的默认值,
 *  它就成了一根不知道多高的柱子。 */
const KIND_PARAMETERS: Partial<Record<SceneObject["kind"], Partial<SceneObject["parameters"]>>> = {
  figure: { height: 1.7, width: 0.45, depth: 0.25 },
  table: { width: 1.4, height: 0.75, depth: 0.8 },
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
    target: [0, 1, 0],
    fov: 45,
    track: [],
    parameters: {
      width: 2,
      height: 2,
      depth: 2,
      radius: 1,
      steps: 8,
      door_width: 1.6,
      door_height: 2.5,
      ...KIND_PARAMETERS[kind],
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
/**
 * 一台机位 + 一个用它的镜头。**它们成对出现** —— 镜头必须指向一台真实存在的相机
 * (后端会拒),所以"新建一个镜头"从来不是只建一个对象。
 */
export function makeShot(name = "镜头 1"): { camera: SceneObject; shot: SceneShot } {
  const camera = makeObject("camera", { name, position: [8, 5, 8], target: [0, 1, 0], fov: 45 });
  return {
    camera,
    shot: { id: uid(), name, duration: 5, aspect: "16:9", easing: "smooth", camera_id: camera.id },
  };
}

/** 拍这个镜头的那台机位。找不到时返回 undefined —— 调用点要自己决定怎么退。 */
export function cameraOfShot(content: SceneContent, shot: SceneShot): SceneObject | undefined {
  return content.objects.find((o) => o.id === shot.camera_id && o.kind === "camera");
}
/** 新场景的默认打光。**和后端 SceneLighting 的默认值同一档**(studio-soft) —— 两边写不一样的
 *  话,新建出来的场景和"重置为默认"会落在不同的光下,而没有任何地方会报错。 */
const DEFAULT_LIGHTING = { preset: "studio-soft", ...presetById("studio-soft")!.values };

export function initialScene(demo = false): SceneContent {
  const { camera, shot } = makeShot();
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
        camera,
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
  camera.name = shot.name;
  // 静止姿态 = 第一帧。轨为空时按它渲,所以两者要一致 —— 否则镜头刚开始播就会跳一下。
  camera.position = [0, 1.6, 5];
  camera.target = [0, 1.6, -1];
  camera.fov = 55;
  camera.track = [
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
      camera,
    ],
    shots: [shot],
    background: "#20242c",
    ambient: 1.8,
  };
}
/**
 * 某个时刻的物体姿态。**空轨就是静止** —— 直接给物体自己的变换。
 *
 * 和相机那条共用同一套语义(端点保持、按镜头的缓动插值),但插的是 position/rotation/scale。
 * 关键帧可以只写其中一部分 —— 没写的字段沿用物体的静止值,这样"只想让它平移"不必把旋转和
 * 缩放也抄一遍。
 */
export function sampleObject(
  object: SceneObject,
  shot: SceneShot,
  time: number,
): { position: Vec3; rotation: Vec3; scale: Vec3 } {
  const still = {
    position: object.position,
    rotation: object.rotation,
    scale: object.scale,
  };
  const track = object.track;
  if (!track.length) return still;
  const t = Math.max(0, Math.min(time, shot.duration));
  const at = (frame: Keyframe) => ({
    position: frame.position,
    rotation: (frame.rotation ?? still.rotation) as Vec3,
    scale: (frame.scale ?? still.scale) as Vec3,
  });
  const next = track.findIndex((f) => f.time > t);
  if (next < 0) return at(track[track.length - 1]);
  if (next === 0) return at(track[0]);
  const a = at(track[next - 1]),
    b = at(track[next]);
  let u = (t - track[next - 1].time) / (track[next].time - track[next - 1].time);
  if (shot.easing === "smooth") u = u * u * (3 - 2 * u);
  const mix = (x: Vec3, y: Vec3) => x.map((v, i) => v + (y[i] - v) * u) as Vec3;
  return {
    position: mix(a.position, b.position),
    rotation: mix(a.rotation, b.rotation),
    scale: mix(a.scale, b.scale),
  };
}

/** 场景里有没有东西在动(相机之外)。决定要不要每帧重算物体的姿态。 */
export function hasObjectMotion(content: SceneContent): boolean {
  return content.objects.some((o) => o.kind !== "camera" && o.track.length > 0);
}

/**
 * 某个时刻的机位姿态。
 *
 * **空轨就是静止** —— 直接给相机物体自己的姿态。这也是"有没有轨"正好等于"动不动"的地方:
 * 一台不动的相机不必带一条只有一帧的轨。
 */
export function sampleCamera(
  camera: SceneObject,
  shot: SceneShot,
  time: number,
): { time: number; position: Vec3; target: Vec3; fov: number } {
  const still = {
    position: camera.position,
    target: camera.target,
    fov: camera.fov,
  };
  const track = camera.track;
  const t = Math.max(0, Math.min(time, shot.duration));
  if (!track.length) return { time: t, ...still };
  const at = (frame: Keyframe) => ({
    position: frame.position,
    target: (frame.target ?? still.target) as Vec3,
    fov: frame.fov ?? still.fov,
  });
  const next = track.findIndex((f) => f.time > t);
  if (next < 0) return { time: t, ...at(track[track.length - 1]) };
  if (next === 0) return { time: t, ...at(track[0]) };
  const a = at(track[next - 1]),
    b = at(track[next]);
  let u = (t - track[next - 1].time) / (track[next].time - track[next - 1].time);
  if (shot.easing === "smooth") u = u * u * (3 - 2 * u);
  const mix = (x: Vec3, y: Vec3) => x.map((v, i) => v + (y[i] - v) * u) as Vec3;
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
  // A shot must keep its camera, including when deleting an ancestor group.
  if (content.shots.some(shot => removed.has(shot.camera_id))) return content;
  return {
    ...content,
    objects: content.objects.filter((o) => !removed.has(o.id)),
  };
}
/** 一个物体和它所有后代的 id。删除、复制、移动都要它 —— 三处此前各写了一遍同一个循环。 */
export function withDescendants(content: SceneContent, id: string): Set<string> {
  const family = new Set([id]);
  let changed = true;
  while (changed) {
    changed = false;
    for (const o of content.objects)
      if (o.parent_id && family.has(o.parent_id) && !family.has(o.id)) {
        family.add(o.id);
        changed = true;
      }
  }
  return family;
}

/**
 * 把一个物体移进某个组(`groupId` 为 null 就是移回顶层)。
 *
 * **这是「组」此前缺的那一半。** 数据模型一直支持 `parent_id`,校验也齐全,但界面上没有任何
 * 入口能把一个已有的物体放进一个已有的组 —— 于是「添加 → 组」建出来的空组是个建完就废的
 * 空盒子,而唯一能用的「编组」只包当前选中的那一个。
 *
 * 挡住两件会让场景变成非法结构的事(后端的 `valid_hierarchy` 也会拒,但那时用户已经点下去了):
 * **不能移进自己的后代**(会形成环),**只有组能装东西**。
 */
export function moveToGroup(
  content: SceneContent,
  id: string,
  groupId: string | null,
): SceneContent {
  const object = content.objects.find((o) => o.id === id);
  if (!object || groupId === id) return content;
  if (groupId !== null) {
    const group = content.objects.find((o) => o.id === groupId);
    if (!group || group.kind !== "group") return content;
    if (withDescendants(content, id).has(groupId)) return content;
  }
  if ((object.parent_id ?? null) === groupId) return content;
  return {
    ...content,
    objects: content.objects.map((o) =>
      o.id === id ? { ...o, parent_id: groupId } : o,
    ),
  };
}

/** 可以把 `id` 移进去的那些组 —— 排除它自己和它的后代(否则就成了环)。 */
export function groupTargets(content: SceneContent, id: string) {
  const family = withDescendants(content, id);
  return content.objects.filter((o) => o.kind === "group" && !family.has(o.id));
}

export function duplicateObject(
  content: SceneContent,
  id: string,
): SceneContent {
  const root = content.objects.find((o) => o.id === id);
  if (!root) return content;
  const descendants = withDescendants(content, id);
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
/**
 * 给一台机位套一条现成的运镜。**返回的是相机的轨,不是镜头** —— 运镜现在长在相机上。
 *
 * 起点取相机当前的静止姿态:用户先摆好一个满意的机位,再选运镜,这是最自然的顺序。
 */
export function cameraPreset(
  camera: SceneObject,
  shot: SceneShot,
  kind: "orbit" | "push",
): Keyframe[] {
  const first: Keyframe = {
    time: 0,
    position: camera.position,
    target: camera.target,
    fov: camera.fov,
  };
  const target = camera.target;
  if (kind === "push")
    return [
      first,
      {
        ...first,
        time: shot.duration,
        position: first.position.map((v, i) => v + (target[i] - v) * 0.5) as Vec3,
      },
    ];
  const dx = first.position[0] - target[0],
    dz = first.position[2] - target[2];
  return Array.from({ length: 9 }, (_, i) => {
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
  });
}
