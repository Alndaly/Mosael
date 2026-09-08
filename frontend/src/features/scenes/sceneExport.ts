import type { Object3D } from "three";

/** Export a detached scene without editor helpers, including helpers inside groups. */
export function cloneSceneForExport(root: Object3D): Object3D {
  const copy = root.clone(true);
  const helpers: Object3D[] = [];
  copy.traverse((node) => {
    if (node.userData.editorOnly) helpers.push(node);
  });
  for (const helper of helpers) helper.removeFromParent();
  return copy;
}
