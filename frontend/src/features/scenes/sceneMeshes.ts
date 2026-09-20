import * as THREE from "three";

import type { SceneObject } from "@/api/domains/scenes";

/**
 * 每种场景物体长什么样 —— 工作台里看到的那一份几何。
 *
 * **它有三个消费者**:这里的 three.js 视口、后端的白模渲染器(`app/domain/scene_render/meshes.py`)、
 * 以及发去 Blender 的 GLB(同一份 meshes.py)。三份实现必须画出同一个东西,否则参考图、
 * 成片和 Blender 里的场景会各是各的,而且错得很安静。一致性由 `contracts/scene-3d-cases.json`
 * 钉住,两侧各跑一遍(`scene3d.parity.test.ts` / `tests/test_scene_3d_parity.py`)。
 *
 * 从 SceneViewport 里搬出来是因为它本来就是个纯函数(物体进、几何出),留在那个一千多行的
 * 组件文件里,契约测试就得把整个视口连同 WebGL 一起拉起来才能验一个立方体多高。
 */
export function geometryObject(o: SceneObject): THREE.Object3D {
  const group = new THREE.Group(),
    p = o.parameters;
  const material = new THREE.MeshStandardMaterial({
    color: o.color,
    roughness: o.roughness,
    metalness: o.metalness,
  });
  function box(w: number, h: number, d: number, x = 0, y = h / 2, z = 0) {
    const m = new THREE.Mesh(new THREE.BoxGeometry(w, h, d), material);
    m.position.set(x, y, z);
    m.castShadow = true;
    m.receiveShadow = true;
    group.add(m);
  }
  if (o.kind === "box") box(p.width, p.height, p.depth);
  if (o.kind === "plane") box(p.width, 0.04, p.depth, 0, -0.02, 0);
  if (o.kind === "sphere" || o.kind === "cylinder") {
    const shape =
      o.kind === "sphere"
        ? new THREE.SphereGeometry(p.radius, 32, 20)
        : new THREE.CylinderGeometry(p.radius, p.radius, p.height, 32);
    const m = new THREE.Mesh(shape, material);
    m.position.y = o.kind === "sphere" ? p.radius : p.height / 2;
    m.castShadow = true;
    m.receiveShadow = true;
    group.add(m);
  }
  if (o.kind === "room") {
    const w = p.width,
      h = p.height,
      d = p.depth,
      door = Math.min(p.door_width, w * 0.85),
      dh = Math.min(p.door_height, h * 0.9),
      side = (w - door) / 2;
    box(w, 0.08, d, 0, -0.04, 0);
    box(0.15, h, d, -w / 2);
    box(0.15, h, d, w / 2);
    for (const z of [-d / 2, d / 2]) {
      box(side, h, 0.15, -(w + door) / 4, h / 2, z);
      box(side, h, 0.15, (w + door) / 4, h / 2, z);
      box(door, h - dh, 0.15, 0, dh + (h - dh) / 2, z);
    }
  }
  if (o.kind === "stairs")
    for (let i = 0; i < p.steps; i++)
      box(
        p.width,
        (p.height * (i + 1)) / p.steps,
        p.depth / p.steps,
        0,
        (p.height * (i + 1)) / p.steps / 2,
        -p.depth / 2 + (p.depth * (i + 0.5)) / p.steps,
      );
  /** 人物。**是给构图当尺子的,不是给人看脸的。**
   *
   * 用几个基本体拼一个概括的人形:关键是高度、肩宽、头的位置和站姿的重心 —— 相机在不在
   * 视平线上、门够不够高、桌子到不到手,靠这几样就判断得出来。做得再细也不会出现在成片里
   * (成片是模型生成的),反而会让人误以为它决定长相。
   *
   * 比例按 1.7 米的常见人体来分:头约 1/7.5 身高,肩宽约 1/4,腿约占下半身。 */
  if (o.kind === "figure") {
    const h = p.height;
    const shoulders = Math.max(p.width, 0.2);
    const thickness = Math.max(p.depth, 0.12);
    const headR = h * 0.066;
    const legH = h * 0.47;
    const torsoH = h * 0.33;
    const capsule = (radius: number, length: number, x: number, y: number, z = 0) => {
      const m = new THREE.Mesh(new THREE.CapsuleGeometry(radius, length, 4, 12), material);
      m.position.set(x, y, z);
      m.castShadow = true;
      m.receiveShadow = true;
      group.add(m);
    };
    // 双腿
    capsule(thickness * 0.42, legH - thickness * 0.84, -shoulders * 0.22, legH / 2);
    capsule(thickness * 0.42, legH - thickness * 0.84, shoulders * 0.22, legH / 2);
    // 躯干:用一个压扁的胶囊,肩比腰宽一点
    const torso = new THREE.Mesh(
      new THREE.CapsuleGeometry(thickness * 0.62, torsoH - thickness * 1.24, 4, 14),
      material,
    );
    torso.scale.set(shoulders / (thickness * 1.24), 1, 1);
    torso.position.y = legH + torsoH / 2;
    torso.castShadow = true;
    torso.receiveShadow = true;
    group.add(torso);
    // 双臂,自然垂在身侧
    const armH = h * 0.36;
    capsule(thickness * 0.3, armH - thickness * 0.6, -shoulders * 0.62, legH + torsoH - armH / 2);
    capsule(thickness * 0.3, armH - thickness * 0.6, shoulders * 0.62, legH + torsoH - armH / 2);
    // 头(含一小截脖子)
    capsule(headR * 0.4, headR * 0.6, 0, legH + torsoH + headR * 0.3);
    const head = new THREE.Mesh(new THREE.SphereGeometry(headR, 24, 16), material);
    head.position.y = h - headR;
    head.castShadow = true;
    head.receiveShadow = true;
    group.add(head);
  }
  /** 桌子:一块台面 + 四条腿。摆道具、定台面高度用 —— 这一页里它出现的频率仅次于地面。 */
  if (o.kind === "table") {
    const top = Math.min(0.06, p.height * 0.1);
    const leg = Math.min(0.08, Math.min(p.width, p.depth) * 0.09);
    box(p.width, top, p.depth, 0, p.height - top / 2);
    for (const sx of [-1, 1])
      for (const sz of [-1, 1])
        box(
          leg,
          p.height - top,
          leg,
          (sx * (p.width - leg)) / 2 * 0.92,
          (p.height - top) / 2,
          (sz * (p.depth - leg)) / 2 * 0.92,
        );
  }
  /** 机位。**它是场景里的物体,所以要看得见、选得中、拖得动。**
   *
   * 视锥按**这台相机真实的 fov** 画,不是一个固定形状 —— 它要能一眼看出"这台拍得宽还是窄"。
   * 机身摆在锥顶**后面**(+Z),因为相机看向 -Z:机身骑在锥顶上的话,近处的东西会被自己的
   * 机身挡住,而且看不出锥是从哪儿发出来的。
   *
   * 标上 editorOnly:它是**编辑期的道具**,不该出现在镜头画面和导出的参考帧里 ——
   * 相机不拍自己。 */
  if (o.kind === "camera") {
    group.userData.editorOnly = true;
    const body = new THREE.Mesh(
      new THREE.BoxGeometry(0.3, 0.22, 0.42),
      new THREE.MeshStandardMaterial({ color: "#8fa2c8", roughness: 0.5, metalness: 0.1 }),
    );
    body.position.z = 0.24;
    group.add(body);
    const reach = 1.1;
    const half = Math.tan(THREE.MathUtils.degToRad(o.fov) / 2) * reach;
    const wide = half * (16 / 9); // 视锥按 16:9 画;比例是镜头的属性,不是相机的
    const corners: [number, number, number][] = [
      [-wide, -half, -reach],
      [wide, -half, -reach],
      [wide, half, -reach],
      [-wide, half, -reach],
    ];
    const points: THREE.Vector3[] = [];
    for (const c of corners)
      points.push(new THREE.Vector3(0, 0, 0), new THREE.Vector3(...c));
    for (let i = 0; i < corners.length; i++)
      points.push(
        new THREE.Vector3(...corners[i]),
        new THREE.Vector3(...corners[(i + 1) % 4]),
      );
    // 顶边中点画一个小三角,标出"哪边朝上" —— 只看一个方框分不出机位有没有翻转。
    points.push(new THREE.Vector3(-wide * 0.4, half, -reach), new THREE.Vector3(0, half * 1.5, -reach));
    points.push(new THREE.Vector3(wide * 0.4, half, -reach), new THREE.Vector3(0, half * 1.5, -reach));
    group.add(
      new THREE.LineSegments(
        new THREE.BufferGeometry().setFromPoints(points),
        new THREE.LineBasicMaterial({ color: "#9fbaff", transparent: true, opacity: 0.9 }),
      ),
    );
  }
  if (o.kind === "light") {
    const lamp = new THREE.PointLight(o.color, o.intensity, 50, 2);
    // 点光源的阴影要渲六个面,比平行光贵得多 —— 给一张小得多的图。它照的通常是局部,
    // 分辨率不够的代价远小于"加了盏灯却没有影子"。
    lamp.castShadow = true;
    lamp.shadow.mapSize.set(512, 512);
    lamp.shadow.bias = -0.005;
    group.add(lamp);
    const bulb = new THREE.Mesh(
      new THREE.SphereGeometry(0.12, 12, 8),
      new THREE.MeshBasicMaterial({ color: o.color }),
    );
    group.add(bulb);
  }
  if (!group.children.length) material.dispose();
  return group;
}
