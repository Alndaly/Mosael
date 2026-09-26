/**
 * 场景编辑器**上次停在哪儿**:看的是哪种视角、哪个镜头、自由视角的相机摆在哪。
 *
 * 此前每次进入场景,视口都按写死的默认机位重建(见 SceneViewport 里 `editorCamera`),视角档
 * 也退回「自由视角」—— 用户刚才绕到背面看的那一眼,出去一趟就没了。
 *
 * **这是个人的编辑器状态,不是场景内容。** 同一个场景换个人打开,该从那个人自己的位置看;
 * 所以它存本地(localStorage),不进 draft、不动 revision、不同步给协作者、也不进后端。
 * 和画布视口(`lib/usePersistentTab` 里的 `usePersistentViewport`)同一个立场、同一套 `mosael:` 前缀。
 *
 * **存进去的东西不一定还是合法的** —— 旧版本写的、手改过、NaN。每一段都单独验,验不过的那段
 * 当没存过、回到默认,绝不能让一条坏数据把视口带进一个转不回来的状态。
 *
 * 相机的上方向不存:编辑相机的 up 永远是 +Y(OrbitControls 只在构造时读一次它,`pose` 也总是
 * 设回 +Y),存它只会多一个能坏的字段。
 */
import type { Vec3 } from "@/api/domains/scenes";

/** 「自由视角 / 机位视角 / 俯瞰全场」。和 SceneStudio 的 `viewMode` 同一组值。 */
export const SCENE_VIEW_MODES = ["edit", "camera", "observe"] as const;
export type SceneViewMode = (typeof SCENE_VIEW_MODES)[number];

/** 一台绕着目标转的相机:站在哪、看着哪、视场多大。 */
export type OrbitView = { position: Vec3; target: Vec3; fov: number };

export type SceneView = {
  mode: SceneViewMode;
  /** 当时选着的镜头。镜头可能已经被删了 —— 调用方要对着当前镜头列表再验一遍。 */
  shotId: string | null;
  /** 自由视角的相机。null = 没存过,用视口自己的默认机位。 */
  free: OrbitView | null;
  /** 「俯瞰全场」里被拖过的取景,连同它当时框的是哪个镜头 —— 换了镜头就该重新框。 */
  overview: (OrbitView & { shotId: string }) | null;
};

export const DEFAULT_SCENE_VIEW: SceneView = { mode: "edit", shotId: null, free: null, overview: null };

const PREFIX = "mosael:scene-view:";
/** 最近用过的那几个场景的 key,新的在前。超出的连同它的记录一起删掉。 */
const RECENT_KEY = "mosael:scene-view-recent";
/**
 * **只记最近 50 个场景。** 每条不到 300 字节,但场景会被建了又删、工作区会换 —— 不封顶就是
 * 一条只增不减的 localStorage。五十个远超一个人来回切换的范围,被挤掉的只是回到默认视角。
 */
export const SCENE_VIEW_LIMIT = 50;

export function sceneViewKey(workspaceId: string, sceneId: string) {
  return `${PREFIX}${workspaceId}:${sceneId}`;
}

const isVec3 = (value: unknown): value is Vec3 =>
  Array.isArray(value) &&
  value.length === 3 &&
  value.every((n) => typeof n === "number" && Number.isFinite(n) && Math.abs(n) < 1e6);

/** 相机和目标重合时轨道控制算不出朝向(球坐标里全是 NaN),视场越界则投影退化 —— 都当坏数据。 */
function parseOrbit(value: unknown): OrbitView | null {
  if (!value || typeof value !== "object") return null;
  const { position, target, fov } = value as Record<string, unknown>;
  if (!isVec3(position) || !isVec3(target)) return null;
  if (typeof fov !== "number" || !Number.isFinite(fov) || fov < 1 || fov > 179) return null;
  const distance = Math.hypot(position[0] - target[0], position[1] - target[1], position[2] - target[2]);
  if (!(distance > 1e-6)) return null;
  return { position: [...position], target: [...target], fov };
}

/** 从存储里的原文解析。整条读不出来 → null;某一段坏了 → 那一段退回默认,其余照用。 */
export function parseSceneView(raw: string | null): SceneView | null {
  if (!raw) return null;
  let value: unknown;
  try {
    value = JSON.parse(raw);
  } catch {
    return null;
  }
  if (!value || typeof value !== "object" || Array.isArray(value)) return null;
  const record = value as Record<string, unknown>;
  const mode = SCENE_VIEW_MODES.includes(record.mode as SceneViewMode)
    ? (record.mode as SceneViewMode)
    : DEFAULT_SCENE_VIEW.mode;
  const shotId = typeof record.shotId === "string" && record.shotId ? record.shotId : null;
  const overviewShot = (record.overview as Record<string, unknown> | null)?.shotId;
  const overviewOrbit = parseOrbit(record.overview);
  return {
    mode,
    shotId,
    free: parseOrbit(record.free),
    overview:
      overviewOrbit && typeof overviewShot === "string" && overviewShot
        ? { ...overviewOrbit, shotId: overviewShot }
        : null,
  };
}

/** 这个场景上次的样子;没存过、读不出来、没有 storage —— 一律是默认值,从不抛。 */
export function readSceneView(workspaceId: string, sceneId: string): SceneView {
  try {
    return parseSceneView(localStorage.getItem(sceneViewKey(workspaceId, sceneId))) ?? DEFAULT_SCENE_VIEW;
  } catch {
    return DEFAULT_SCENE_VIEW;
  }
}

function readRecent(): string[] {
  try {
    const parsed: unknown = JSON.parse(localStorage.getItem(RECENT_KEY) ?? "[]");
    return Array.isArray(parsed) ? parsed.filter((key): key is string => typeof key === "string") : [];
  } catch {
    return [];
  }
}

/**
 * 并进去一部分。视角档和镜头由 SceneStudio 写,相机由视口写,**两边各写各的那几段**,
 * 不会互相抹掉。写完把这个场景挪到最近列表的最前面,挤出去的删掉。
 */
export function writeSceneView(workspaceId: string, sceneId: string, patch: Partial<SceneView>) {
  const key = sceneViewKey(workspaceId, sceneId);
  try {
    const next: SceneView = { ...readSceneView(workspaceId, sceneId) };
    for (const [field, value] of Object.entries(patch) as [keyof SceneView, never][])
      if (value !== undefined) next[field] = value;
    localStorage.setItem(key, JSON.stringify(next));
    const recent = [key, ...readRecent().filter((one) => one !== key)];
    for (const evicted of recent.splice(SCENE_VIEW_LIMIT)) localStorage.removeItem(evicted);
    localStorage.setItem(RECENT_KEY, JSON.stringify(recent));
  } catch {
    /* 隐私模式 / 配额满:这次会话照常用,只是下次回来还是默认视角。 */
  }
}

/** 场景删掉了,它的视角也不用留。 */
export function forgetSceneView(workspaceId: string, sceneId: string) {
  const key = sceneViewKey(workspaceId, sceneId);
  try {
    localStorage.removeItem(key);
    localStorage.setItem(RECENT_KEY, JSON.stringify(readRecent().filter((one) => one !== key)));
  } catch {
    /* 留着一条也无妨:最近列表迟早把它挤掉。 */
  }
}

/** 对着当前镜头列表验一遍存着的镜头 —— 被删了就回到第一个。 */
export function rememberedShot(view: SceneView, shots: readonly { id: string }[]): string {
  return view.shotId && shots.some((shot) => shot.id === view.shotId) ? view.shotId : shots[0].id;
}

/**
 * 相机在动时的存盘节流:**最多每 `ms` 写一次**,停下来之后补上最后那一下。
 *
 * 轨道控制的 change 在拖动和阻尼期间每帧都触发,逐帧 JSON 序列化再写 localStorage 是纯浪费;
 * 而只在 end 时存又会漏掉阻尼滑行完的终点、滚轮缩放(它没有 end)。`flush` 给卸载和关页面用 ——
 * 那时还挂着的那一次必须立刻落下。
 */
export function throttledSave(save: () => void, ms = 300) {
  let timer: ReturnType<typeof setTimeout> | null = null;
  const flush = () => {
    if (timer === null) return;
    clearTimeout(timer);
    timer = null;
    save();
  };
  return {
    schedule() {
      if (timer === null) timer = setTimeout(flush, ms);
    },
    flush,
  };
}

/** 能被存下来的最小相机接口 —— 视口里是 three 的相机和 OrbitControls,测试里也可以是它们。 */
type OrbitCamera = {
  position: { x: number; y: number; z: number; set: (x: number, y: number, z: number) => unknown };
  up: { set: (x: number, y: number, z: number) => unknown };
  fov: number;
  far: number;
  updateProjectionMatrix: () => void;
};
type OrbitTarget = {
  target: { x: number; y: number; z: number; set: (x: number, y: number, z: number) => unknown };
  update: () => unknown;
};

export function captureOrbit(camera: OrbitCamera, controls: OrbitTarget): OrbitView {
  const { position: p } = camera,
    { target: t } = controls;
  return { position: [p.x, p.y, p.z], target: [t.x, t.y, t.z], fov: camera.fov };
}

/**
 * 把相机摆回存着的样子。远裁剪面按距离放宽 —— 和「聚焦」同一条规则,否则拉得很远的视角
 * 回来时远处的东西会被裁掉。
 */
export function applyOrbit(camera: OrbitCamera, controls: OrbitTarget, view: OrbitView) {
  camera.up.set(0, 1, 0);
  camera.position.set(...view.position);
  controls.target.set(...view.target);
  camera.fov = view.fov;
  const distance = Math.hypot(
    view.position[0] - view.target[0],
    view.position[1] - view.target[1],
    view.position[2] - view.target[2],
  );
  camera.far = Math.max(2000, distance * 10);
  camera.updateProjectionMatrix();
  controls.update();
}
