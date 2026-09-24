import { Box3, type BufferGeometry, type Object3D } from "three";

/**
 * Export a detached scene without editor helpers, including helpers inside groups.
 *
 * **藏起来的物体(`visible === false`)也整支摘掉,连同后代。** 三条出片的路都从这里拿场景:
 * 参考帧(`frame`)、参考视频(`record`)和 GLB。前两条交给渲染器时本来就跳过不可见节点,
 * GLTFExporter 也默认 `onlyVisible` —— 但那是三处各自的默认值碰巧一致,而其中藏起来的灯
 * 仍会留在导出场景里占着。在这里摘掉,"藏了就不出片"只有这一处说了算。
 *
 * 相机的道具(editorOnly)在视口里按视图切换可见性,所以它**不靠**这条规则,而是无条件摘:
 * 藏没藏都一样 —— 相机不拍自己;而"藏起来的相机"仍能当镜头的机位用(镜头看的是数据,不是
 * 这个道具,见 SceneViewport 里 `frameAt`)。
 */
export function cloneSceneForExport(root: Object3D): Object3D {
  const copy = root.clone(true);
  const dropped: Object3D[] = [];
  copy.traverse((node) => {
    if (node !== copy && (node.userData.editorOnly || !node.visible)) dropped.push(node);
  });
  for (const node of dropped) node.removeFromParent();
  return copy;
}

/**
 * 看得见的那些东西的包围盒。**藏起来的物体不参与取景和打光。**
 *
 * `Box3.setFromObject` 不看可见性:一个藏起来的大地面会把主光的阴影盒子撑大(影子变糊)、
 * 把「聚焦全部」「俯瞰全场」的取景拉远到一片空白。`traverseVisible` 连后代一起跳过。
 */
export function visibleBounds(root: Object3D): Box3 {
  const bounds = new Box3(),
    part = new Box3();
  root.updateWorldMatrix(true, true);
  root.traverseVisible((node) => {
    const geometry = (node as Object3D & { geometry?: BufferGeometry }).geometry;
    if (!geometry) return;
    if (!geometry.boundingBox) geometry.computeBoundingBox();
    bounds.union(part.copy(geometry.boundingBox!).applyMatrix4(node.matrixWorld));
  });
  return bounds;
}
