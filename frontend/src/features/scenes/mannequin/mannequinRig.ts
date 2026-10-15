import * as THREE from "three";

import type { FigurePose } from "@/api/domains/scenes";

/**
 * 程序化内置人偶:three.js 图元拼的、关节分层的摆姿势模型。**零外部资产** —— 素材全在代码里。
 *
 * 动机:人物建模是 Mosael 的薄弱处,而人偶**摆好的形态**才是要交给生图模型的条件。所以这颗
 * 人偶是「姿势 → 着色快照 → 素材库 → 生图参考图」这条链的第一环,它自己不需要好看,需要
 * **比例协调、关节转得对、形态读得清**。
 *
 * 关节层级(每个关节一个 Object3D pivot,肢体段挂在对应关节下 —— 子随父动,FK 天然成立):
 *
 *     hips → spine → chest → neck → head
 *     chest → shoulder.L/R → upperArm.L/R → forearm.L/R → hand.L/R
 *     hips  → thigh.L/R → shin.L/R → foot.L/R
 *
 * 每个 pivot 的局部坐标里,四肢段沿 **-Y** 下垂、角色面朝 **+Z**:
 *   - 转 X 负角 = 肢体往前方(+Z)摆;转 X 正角 = 往后。
 *   - 手臂绕 Z:左臂(在 +X 侧)正角向外抬成 T 字,负角贴向身体;右臂镜像。
 *
 * 比例按 1.7 米常见的风格化人形:头约占 1/7.5 身高、肩宽(上臂外缘)0.47 米 ≈ 身高的 0.28、腿约占下半身。
 * 材质是**一份**单色哑光的木头人偶料(少量 mesh 共享一份材质,快照和视口都靠它读出体积)。
 */

/** 全部关节名。**名字就是数据**:姿势表、拾取、快照都认这套键。 */
export const MANNEQUIN_JOINTS = [
  "hips",
  "spine",
  "chest",
  "neck",
  "head",
  "shoulderL",
  "upperArmL",
  "forearmL",
  "handL",
  "shoulderR",
  "upperArmR",
  "forearmR",
  "handR",
  "thighL",
  "shinL",
  "footL",
  "thighR",
  "shinR",
  "footR",
] as const;

export type MannequinJoint = (typeof MANNEQUIN_JOINTS)[number];

export function isMannequinJoint(name: string): name is MannequinJoint {
  return (MANNEQUIN_JOINTS as readonly string[]).includes(name);
}

/**
 * 一个姿势:关节 → 欧拉角(度),外加可选的髋部下移。**坐/蹲必须能把身体放下去** ——
 * 纯旋转做不到(髋 pivot 钉在站姿高度),所以姿势表带一个 `hipsDrop`(米):
 * 坐下时髋从 0.95 落到 ~0.5(椅子高),蹲再低一点。
 */
export type MannequinPose = {
  angles: Partial<Record<MannequinJoint, [number, number, number]>>;
  hipsDrop?: number;
};

/**
 * 场景对象里的 pose(见 api/domains/scenes.FigurePose)→ 人偶姿势表:`hips_drop` 蛇形换驼峰。
 * 人偶代码内部用驼峰 `hipsDrop`;场景数据持久化用蛇形(和 entity_id、model_id 一样)。
 */
export function poseToMannequin(pose: FigurePose | null | undefined): MannequinPose {
  return {
    angles: (pose?.angles ?? {}) as MannequinPose["angles"],
    hipsDrop: pose?.hips_drop ?? 0,
  };
}

/** 人偶姿势表 → 场景对象的 pose(髋没下沉就不写那个键)。 */
export function poseFromMannequin(pose: MannequinPose): FigurePose {
  return {
    angles: pose.angles as Record<string, [number, number, number]>,
    ...(pose.hipsDrop ? { hips_drop: pose.hipsDrop } : {}),
  };
}

export type MannequinRig = {
  /** 人偶根(脚底在 y=0,面朝 +Z)。挂进场景、传给快照渲染都用它。 */
  root: THREE.Group;
  /** 关节名 → pivot。旋转 pivot = FK。 */
  joints: ReadonlyMap<MannequinJoint, THREE.Object3D>;
  /** 所有肢体 mesh(射线拾取的对象)。 */
  meshes: THREE.Mesh[];
  /** 全身共用的一份哑光材质。 */
  material: THREE.MeshStandardMaterial;
  /** 从任意节点(拾取命中的 mesh)往上找它属于哪个关节;pivot 自己也算。 */
  jointOf: (object: THREE.Object3D | null | undefined) => MannequinJoint | null;
  dispose: () => void;
};

/** 默认身高(米)。所有比例从它推。 */
export const MANNEQUIN_HEIGHT = 1.7;

/** 木头人偶的哑光色:暖木色,粗糙度拉高,没有高光点,关节走向读得清。 */
export const MANNEQUIN_MATERIAL = { color: 0xc59a68, roughness: 0.82, metalness: 0.02 };

export function createMannequin(
  height = MANNEQUIN_HEIGHT,
  material?: THREE.MeshStandardMaterial,
): MannequinRig {
  const s = height / MANNEQUIN_HEIGHT;
  const ownsMaterial = material === undefined;
  const materialFor = material ?? new THREE.MeshStandardMaterial({
    color: MANNEQUIN_MATERIAL.color,
    roughness: MANNEQUIN_MATERIAL.roughness,
    metalness: MANNEQUIN_MATERIAL.metalness,
  });
  const geometries: THREE.BufferGeometry[] = [];
  const meshes: THREE.Mesh[] = [];
  const joints = new Map<MannequinJoint, THREE.Object3D>();

  const root = new THREE.Group();
  root.name = "mannequin";

  /** 关节 pivot:它自己的朝向就是 FK 的转轴,位置在骨骼连接点上。 */
  function pivot(
    name: MannequinJoint,
    parent: THREE.Object3D,
    x: number,
    y: number,
    z: number,
  ): THREE.Object3D {
    const node = new THREE.Object3D();
    node.name = `joint:${name}`;
    node.position.set(x * s, y * s, z * s);
    node.userData.mannequinJoint = name;
    parent.add(node);
    joints.set(name, node);
    return node;
  }

  /** 肢体段:胶囊(两头圆、像木头人的连杆),挂在 proximal 关节下、沿 -Y 伸。 */
  function segment(
    joint: MannequinJoint,
    radius: number,
    length: number,
    y: number,
    scaleX = 1,
    scaleZ = 1,
  ): THREE.Mesh {
    const geometry = new THREE.CapsuleGeometry(radius * s, length * s, 4, 14);
    const mesh = new THREE.Mesh(geometry, materialFor);
    mesh.position.y = y * s;
    mesh.scale.set(scaleX, 1, scaleZ);
    mesh.castShadow = true;
    mesh.receiveShadow = true;
    mesh.userData.mannequinJoint = joint;
    geometries.push(geometry);
    meshes.push(mesh);
    joints.get(joint)!.add(mesh);
    return mesh;
  }

  // ── 中轴:髋 → 脊柱 → 胸 → 颈 → 头 ─────────────────────────────────────────
  // 脚底 y=0,髋在 0.95(腿占下半身),颈根 ~1.48,头顶 ~1.75。
  const hips = pivot("hips", root, 0, 0.95, 0);
  segment("hips", 0.135, 0.1, 0.03, 1.2, 0.85); // 骨盆
  const spine = pivot("spine", hips, 0, 0.15, 0);
  segment("spine", 0.125, 0.16, 0.09, 1.1, 0.8); // 腰段
  const chest = pivot("chest", spine, 0, 0.2, 0);
  // 胸廓:**顶 1.46 以上到颈根 1.516 那一段只能有脖子**,所以胸顶收在 1.46。three 的胶囊半高 =
  // length/2 + radius,所以 [0.15, 0.02] @ 段心 0 的胸廓是 1.30 ± 0.16 = [1.14, 1.46]:仍够宽
  // (半宽 0.195,和原来一样),但顶从 1.63 收到 1.46。原来 length 0.18 那版一路顶到 1.63,把
  // [1.43,1.59] 的脖子和头的下缘(头根 1.516)全包了进去 —— 那才是「没脖子」的真因,不是脖子缺几何。
  segment("chest", 0.15, 0.02, 0, 1.3, 0.78); // 胸廓(肩比腰宽)
  const neck = pivot("neck", chest, 0, 0.18, 0);
  // 脖子:略加长加粗(0.05/0.06 @ 0.03 → 0.052/0.06 @ 0.02),占 [1.42, 1.58]:
  // 下段 1.42–1.46 埋在胸里接住躯干,1.46–1.516 露在外面,冠顶 1.58 顶进头根(头根 1.516)。
  segment("neck", 0.052, 0.06, 0.02);
  const head = pivot("head", neck, 0, 0.06, 0);
  {
    const geometry = new THREE.SphereGeometry(0.115 * s, 24, 18);
    const mesh = new THREE.Mesh(geometry, materialFor);
    mesh.position.y = 0.1 * s;
    mesh.scale.set(0.92, 1.08, 0.98);
    mesh.castShadow = true;
    mesh.receiveShadow = true;
    mesh.userData.mannequinJoint = "head";
    geometries.push(geometry);
    meshes.push(mesh);
    head.add(mesh);
  }

  // ── 手臂:胸 → 肩 → 上臂 → 前臂 → 手(左在 +X 侧,面朝 +Z)──────────────────
  // 肩这一组整块跟着胸廓往下收。**此前肩 pivot 就钉在胸顶 1.46 上**:锁骨横到 ±0.24、上臂根在
  // ±0.21,而胸半宽只有 0.195 —— 锁骨和上臂根既在胸宽之外、顶又高过胸顶(锁骨顶 1.505、上臂顶
  // 1.485),所以读起来是「一副衣架架在圆胸上」。三处一起改:
  //   - 肩 pivot 沉到 1.41(胸 [1.14,1.46] 的上段),胸顶那 5cm 留出来当斜方肌的坡,肩不再骑在顶边;
  //   - 锁骨 length 0.08 → 0.04、x 偏移 0.055 → 0.05 → 跨 [0.065, 0.195]:**最外缘正好等于胸半宽**,
  //     顶 1.455 也压在胸顶 1.46 之下,于是它读作肩头而不是横梁;
  //   - 上臂根 0.21 → 0.18(胸最宽处 0.195):上臂胶囊的内半边叠进胸廓侧面,不再是悬在外面的柱子。
  // 「胸 → 肩 → 上臂」因此是一个连着的体块。脖子照旧露出 1.46–1.516(这段里没放任何几何)。
  for (const side of ["L", "R"] as const) {
    const sign = side === "L" ? 1 : -1;
    const shoulder = pivot(`shoulder${side}` as MannequinJoint, chest, sign * 0.08, 0.11, 0);
    // 锁骨:横躺的小胶囊,收在胸宽里、落在胸的上段 —— 肩头,不是横梁。
    {
      const geometry = new THREE.CapsuleGeometry(0.045 * s, 0.04 * s, 4, 10);
      const mesh = new THREE.Mesh(geometry, materialFor);
      mesh.rotation.z = Math.PI / 2;
      mesh.position.x = (sign * 0.05 * s);
      mesh.castShadow = true;
      mesh.receiveShadow = true;
      mesh.userData.mannequinJoint = `shoulder${side}`;
      geometries.push(geometry);
      meshes.push(mesh);
      shoulder.add(mesh);
    }
    const upperArm = pivot(`upperArm${side}` as MannequinJoint, shoulder, sign * 0.1, 0, 0);
    segment(`upperArm${side}` as MannequinJoint, 0.055, 0.17, -0.115);
    const forearm = pivot(`forearm${side}` as MannequinJoint, upperArm, 0, -0.23, 0);
    segment(`forearm${side}` as MannequinJoint, 0.047, 0.15, -0.1);
    pivot(`hand${side}` as MannequinJoint, forearm, 0, -0.21, 0);
    segment(`hand${side}` as MannequinJoint, 0.05, 0.09, -0.065);
  }

  // ── 腿:髋 → 大腿 → 小腿 → 脚 ──────────────────────────────────────────────
  for (const side of ["L", "R"] as const) {
    const sign = side === "L" ? 1 : -1;
    const thigh = pivot(`thigh${side}` as MannequinJoint, hips, sign * 0.105, -0.03, 0);
    segment(`thigh${side}` as MannequinJoint, 0.085, 0.27, -0.19);
    const shin = pivot(`shin${side}` as MannequinJoint, thigh, 0, -0.4, 0);
    segment(`shin${side}` as MannequinJoint, 0.063, 0.27, -0.18);
    // 脚踝上提 0.02(-0.4 → -0.38,世界 0.12 → 0.14):原来的 -0.4 把脚面留在 0.107,小腿底
    // 0.142,中间空 0.035 —— 脚看着就是飘着的小方块。
    const foot = pivot(`foot${side}` as MannequinJoint, shin, 0, -0.38, 0);
    // 脚:盒子(脚掌 + 踝)。盒心 -0.07、高 0.14 → 世界 [0.0, 0.14]:**脚底落在 y=0**,顶面
    // 盖过小腿底 0.142,小腿末端整个坐在脚里,不再有缝;深 0.25、中心 z 0.045 → 脚跟 -0.08 /
    // 脚尖 0.17(和原来一样),也不再是那个小方块。
    {
      const geometry = new THREE.BoxGeometry(0.09 * s, 0.14 * s, 0.25 * s);
      const mesh = new THREE.Mesh(geometry, materialFor);
      mesh.position.set(0, -0.07 * s, 0.045 * s);
      mesh.castShadow = true;
      mesh.receiveShadow = true;
      mesh.userData.mannequinJoint = `foot${side}`;
      geometries.push(geometry);
      meshes.push(mesh);
      foot.add(mesh);
    }
  }

  const jointOf = (object: THREE.Object3D | null | undefined): MannequinJoint | null => {
    for (let node = object ?? null; node; node = node.parent) {
      const name = node.userData.mannequinJoint;
      if (typeof name === "string" && isMannequinJoint(name)) return name;
    }
    return null;
  };

  return {
    root,
    joints,
    meshes,
    material: materialFor,
    jointOf,
    dispose: () => {
      geometries.forEach((geometry) => geometry.dispose());
      if (ownsMaterial) materialFor.dispose();
    },
  };
}

/** 把姿势表(度)写进关节 pivot,髋部下移到位。复位请先 `resetPose`。 */
export function applyPose(rig: MannequinRig, pose: MannequinPose) {
  for (const [name, [x, y, z]] of Object.entries(pose.angles)) {
    if (!isMannequinJoint(name)) continue;
    const joint = rig.joints.get(name)!;
    joint.rotation.set(
      THREE.MathUtils.degToRad(x),
      THREE.MathUtils.degToRad(y),
      THREE.MathUtils.degToRad(z),
    );
  }
  const hips = rig.joints.get("hips")!;
  // 站姿时髋 pivot 的局部高度记一份,drop 相对它算 —— 反复应用预设不会一路降下去。
  hips.userData.restY ??= hips.position.y;
  hips.position.y = (hips.userData.restY as number) - (pose.hipsDrop ?? 0);
}

/** 读出当前姿势(度):全部关节的欧拉角,可当快照/存姿势的输入。 */
export function readPose(rig: MannequinRig): Record<MannequinJoint, [number, number, number]> {
  const pose = {} as Record<MannequinJoint, [number, number, number]>;
  for (const name of MANNEQUIN_JOINTS) {
    const { x, y, z } = rig.joints.get(name)!.rotation;
    pose[name] = [
      Math.round(THREE.MathUtils.radToDeg(x) * 10) / 10,
      Math.round(THREE.MathUtils.radToDeg(y) * 10) / 10,
      Math.round(THREE.MathUtils.radToDeg(z) * 10) / 10,
    ];
  }
  return pose;
}

/** 复位:所有关节归零、髋回到站姿高度(直立、面朝 +Z)。 */
export function resetPose(rig: MannequinRig) {
  for (const name of MANNEQUIN_JOINTS) rig.joints.get(name)!.rotation.set(0, 0, 0);
  const hips = rig.joints.get("hips")!;
  if (typeof hips.userData.restY === "number") hips.position.y = hips.userData.restY;
}
