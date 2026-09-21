/**
 * 地面网格。**着色器画的,没有边。**
 *
 * 此前是一块 `THREE.GridHelper(40, 40)` —— 写死 40 米见方的线段网格,摆在原点不动。于是:
 * 到 ±20 米就断,断口是一条直边;而轨道控制允许拉到 1000 米,飞出二十米之后地面参照直接没了;
 * 远处的线因为不透明度恒定,还会糊成摩尔纹。
 *
 * Blender 的网格不是几何体,是着色器按世界坐标算出来的。这一份照同一条路走:
 *
 * - **格线宽度按屏幕算**(`fwidth`),所以近处不粗、远处不糊,永远是一像素上下;
 * - **格距随相机距离换档**(1 → 10 → 100 米……),细档在拉远时淡出,换档处是渐变不是跳变 ——
 *   固定格距的网格拉远之后是一片实心色,拉近又只剩几条线;
 * - **淡出半径跟着相机距离走**,不是一个固定值。所以拉到几百米时网格**还在**,仍然占着
 *   差不多大的一块画面 —— 这正是"无限"该有的手感。固定半径的话,拉远一点就整个消失了。
 * - X / Z 轴线各自带一点红和蓝。白模摆位时"哪边是前"全靠它,而纯灰的网格说不出这件事。
 *
 * 承载它的是一块平面,每帧跟着相机的水平位置走、按距离缩放。**这不会让图案跟着动** ——
 * 图案是按世界坐标算的,平面只是决定"画在哪块像素上"。
 */

import * as THREE from "three";

export interface InfiniteGrid {
  object: THREE.Mesh;
  /** 每帧调一次:把承载面挪到相机脚下,并把当前距离交给着色器。 */
  update(camera: THREE.Camera): void;
  dispose(): void;
}

const VERTEX = /* glsl */ `
varying vec3 vWorld;
void main() {
  vWorld = (modelMatrix * vec4(position, 1.0)).xyz;
  gl_Position = projectionMatrix * viewMatrix * vec4(vWorld, 1.0);
}
`;

const FRAGMENT = /* glsl */ `
precision highp float;
varying vec3 vWorld;
uniform vec3 uCamera;
uniform vec3 uColor;
uniform vec3 uAxisX;
uniform vec3 uAxisZ;
uniform float uOpacity;
uniform float uCell;      // 当前细档格距(米)
uniform float uBlend;     // 0 → 细档全亮;1 → 细档已淡尽,由中档接手
uniform float uFade;      // 淡出半径(米)

/** 一张格距为 cell 的网格在这一点的覆盖度。宽度按屏幕导数算,所以远近一样细。 */
float lines(vec2 p, float cell) {
  vec2 grid = p / cell;
  vec2 d = abs(fract(grid - 0.5) - 0.5) / fwidth(grid);
  return 1.0 - min(min(d.x, d.y), 1.0);
}

void main() {
  vec2 p = vWorld.xz;
  float fine = lines(p, uCell) * (1.0 - uBlend);
  float mid = lines(p, uCell * 10.0);
  float coarse = lines(p, uCell * 100.0) * uBlend;
  float line = max(max(fine, mid), coarse);
  if (line <= 0.001) discard;

  // 轴线:比一格还窄时才算,否则拉远之后整条轴会胖成一道带子。
  vec2 axis = abs(p) / fwidth(p);
  vec3 color = uColor;
  if (axis.y < 1.0) color = uAxisX;        // 沿 X 走的那条线(z = 0)
  else if (axis.x < 1.0) color = uAxisZ;   // 沿 Z 走的那条线(x = 0)

  // 淡出半径跟着相机距离走 —— 拉远时网格还在,而不是整个消失。
  float far = 1.0 - smoothstep(uFade * 0.55, uFade, distance(uCamera.xz, p));
  float alpha = line * far * uOpacity;
  if (alpha <= 0.002) discard;
  gl_FragColor = vec4(color, alpha);
}
`;

/** 相机离地面多远 —— 换档和淡出半径都按它算。贴地时也给一个下限,否则格距会掉到毫米级。 */
function groundDistance(camera: THREE.Camera): number {
  const position = new THREE.Vector3();
  camera.getWorldPosition(position);
  return Math.max(2, Math.hypot(position.y, 0) || 2, position.length() * 0.35);
}

export function createInfiniteGrid(options?: {
  color?: number;
  axisX?: number;
  axisZ?: number;
  opacity?: number;
  y?: number;
}): InfiniteGrid {
  const material = new THREE.ShaderMaterial({
    vertexShader: VERTEX,
    fragmentShader: FRAGMENT,
    transparent: true,
    // 网格是参照物,不该挡住任何东西,也不该写进深度 —— 写了的话它下面的物体会被剔掉。
    depthWrite: false,
    side: THREE.DoubleSide,
    uniforms: {
      uCamera: { value: new THREE.Vector3() },
      uColor: { value: new THREE.Color(options?.color ?? 0x6b7480) },
      uAxisX: { value: new THREE.Color(options?.axisX ?? 0x9c5f68) },
      uAxisZ: { value: new THREE.Color(options?.axisZ ?? 0x5a6f9c) },
      uOpacity: { value: options?.opacity ?? 0.6 },
      uCell: { value: 1 },
      uBlend: { value: 0 },
      uFade: { value: 60 },
    },
  });
  const object = new THREE.Mesh(new THREE.PlaneGeometry(1, 1), material);
  object.rotation.x = -Math.PI / 2;
  object.position.y = options?.y ?? -0.09;
  // 网格永远在取景之外也成立,不该参与自动取景(fitShadow / frameAll 都按包围盒算)。
  object.frustumCulled = false;
  object.renderOrder = -1;
  object.matrixAutoUpdate = true;

  const camPosition = new THREE.Vector3();
  return {
    object,
    update(camera) {
      camera.getWorldPosition(camPosition);
      const distance = groundDistance(camera);
      // 细档取「看得清的那一档」:距离每涨十倍,格距涨十倍。
      const lod = Math.log10(distance * 0.12);
      const step = Math.floor(lod);
      material.uniforms.uCell.value = Math.pow(10, step);
      material.uniforms.uBlend.value = lod - step;
      material.uniforms.uFade.value = distance * 9;
      material.uniforms.uCamera.value.copy(camPosition);
      // 承载面跟着相机走并按距离放大:它只决定画在哪块像素上,图案仍按世界坐标算,
      // 所以跟着走**不会**让网格滑动。
      object.position.x = camPosition.x;
      object.position.z = camPosition.z;
      object.scale.setScalar(distance * 24);
    },
    dispose() {
      object.geometry.dispose();
      material.dispose();
    },
  };
}
