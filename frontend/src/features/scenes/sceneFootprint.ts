/**
 * 场景的**俯视占地** —— 每个物体在地面上压出多大一块、朝向哪边。
 *
 * 缩略图不该是截图。画板和工作流的卡片(CanvasPreview)都是从保存的数据直出一张 SVG,好处是
 * 它永远和数据同步:场景改了缩略图跟着变,不会停在"上次保存那一刻"。3D 这边同理 —— 而且
 * 列表页要是给每张卡片起一个 WebGL 上下文,五张卡片就是五个,这条路一开始就不能走。
 *
 * **和视口的造型知识是什么关系**:视口(SceneViewport)按同一批 parameters 建 three.js 的 mesh,
 * 这里只取它压在地面上的那个矩形。两边共用的是 `parameters` 的含义(width/depth/radius 各指
 * 什么),而不是建模过程本身 —— 所以这个模块不依赖 three,可以单测。
 */

/** 预览用的物体:后端 `scene_preview` 挑出来的那几个字段,不含造型解释。 */
export interface PreviewObject {
  kind: string;
  position?: [number, number, number] | null;
  rotation?: [number, number, number] | null;
  scale?: [number, number, number] | null;
  color?: string | null;
  parameters?: { width?: number; depth?: number; radius?: number } | null;
  /** 相机才有:运镜轨上的位置点。 */
  path?: ([number, number, number] | null)[] | null;
}

export interface ScenePreviewData {
  objects?: PreviewObject[] | null;
}

/** 地面上的一块:中心 (x, z)、宽深 (w, d)、绕 Y 的角度(度)。 */
export interface Footprint {
  x: number;
  z: number;
  w: number;
  d: number;
  angle: number;
  color: string;
  kind: string;
}

const num = (value: unknown, fallback: number) =>
  typeof value === "number" && Number.isFinite(value) ? value : fallback;

/**
 * 一个物体压在地面上的宽和深(**未乘 scale**)。
 *
 * 按 kind 分:方体类用 width×depth,圆体类用直径见方,而相机/灯这些没有实体的东西给一个
 * 固定的小方块 —— 它们在缩略图上是**位置标记**,不是占地。
 */
function extent(object: PreviewObject): [number, number] {
  const p = object.parameters ?? {};
  const width = num(p.width, 2);
  const depth = num(p.depth, 2);
  const radius = num(p.radius, 1);
  switch (object.kind) {
    case "sphere":
    case "cylinder":
      return [radius * 2, radius * 2];
    case "camera":
    case "light":
      return [0.6, 0.6];
    case "figure":
      return [0.5, 0.5];
    // box / plane / room / stairs / table / group / model 都按 width×depth 摊开。
    // group 和 model 没有自己的 parameters,落到默认 2×2 —— 一个"这儿有东西"的占位,
    // 比不画强:group 的子物体本来就各自画了,model 的真实包围盒只有加载过网格才知道。
    default:
      return [width, depth];
  }
}

/** 把预览数据摊成地面上的一组矩形。隐藏物体后端已经滤掉了。 */
export function footprints(data: ScenePreviewData | null | undefined): Footprint[] {
  return (data?.objects ?? []).map((object) => {
    const [width, depth] = extent(object);
    const scale = object.scale ?? [1, 1, 1];
    const position = object.position ?? [0, 0, 0];
    return {
      x: num(position[0], 0),
      z: num(position[2], 0),
      w: Math.max(0.05, width * num(scale[0], 1)),
      d: Math.max(0.05, depth * num(scale[2], 1)),
      angle: num((object.rotation ?? [0, 0, 0])[1], 0),
      color: typeof object.color === "string" ? object.color : "#b4bccb",
      kind: object.kind,
    };
  });
}

/** 相机走过的地面路线。少于两点就没有"路线"可言(静止机位),返回空。 */
export function cameraPaths(data: ScenePreviewData | null | undefined): [number, number][][] {
  const paths: [number, number][][] = [];
  for (const object of data?.objects ?? []) {
    const points = (object.path ?? [])
      .filter((point): point is [number, number, number] => Array.isArray(point))
      .map((point) => [num(point[0], 0), num(point[2], 0)] as [number, number]);
    if (points.length > 1) paths.push(points);
  }
  return paths;
}

/** 把所有占地和路线框起来的那个矩形,留一点边。空场景给一块默认地。 */
export function bounds(marks: Footprint[], paths: [number, number][][]) {
  const xs: number[] = [];
  const zs: number[] = [];
  for (const mark of marks) {
    // 旋转过的矩形用外接圆半径估,省得为了缩略图去算四个角 —— 宁可框大一点,也不要裁掉一角。
    const reach = Math.hypot(mark.w, mark.d) / 2;
    xs.push(mark.x - reach, mark.x + reach);
    zs.push(mark.z - reach, mark.z + reach);
  }
  for (const path of paths) for (const [x, z] of path) { xs.push(x); zs.push(z); }
  if (!xs.length) return { x: -5, z: -5, w: 10, d: 10 };
  const minX = Math.min(...xs), maxX = Math.max(...xs);
  const minZ = Math.min(...zs), maxZ = Math.max(...zs);
  const pad = Math.max(1, Math.max(maxX - minX, maxZ - minZ) * 0.08);
  return { x: minX - pad, z: minZ - pad, w: maxX - minX + pad * 2, d: maxZ - minZ + pad * 2 };
}
