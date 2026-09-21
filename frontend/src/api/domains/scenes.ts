import type { components } from "@/api/generated/schema";
import { api, API_BASE, getAuthToken } from "@/api/transport";
export type Vec3 = [number, number, number];

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

/** 时间轨上的一个时刻。相机用 position + target + fov,物体用 position + rotation + scale。
 *  没填的字段表示"这一档不控制它" —— 所以这里**不能** Required。 */
export type Keyframe = components["schemas"]["Keyframe"] & { time: number; position: Vec3 };
export type SceneObject = Omit<
  Required<components["schemas"]["SceneObject"]>,
  "parameters" | "track"
> & {
  parameters: Required<components["schemas"]["ShapeParameters"]>;
  /** 空的就是静止 —— 绝大多数物体都是空的。 */
  track: Keyframe[];
};
/** 镜头 = 用哪台机位、拍多久。运镜是那台相机物体的 track,见 docs/design/scene-time-and-cameras.md。 */
export type SceneShot = Required<components["schemas"]["SceneShot"]>;
export type SceneContent = Omit<
  Required<components["schemas"]["SceneContent"]>,
  "objects" | "shots"
> & { objects: SceneObject[]; shots: SceneShot[] };
export type SceneLighting = Required<components["schemas"]["SceneLighting"]>;
export type Scene = Omit<components["schemas"]["SceneOut"], "content"> & {
  content: SceneContent;
};
export type SceneSummary = Pick<
  Scene,
  "id" | "name" | "revision" | "updated_at"
> & { object_count: number; shot_count: number; preview?: ScenePreviewData };
const query = (ws: string) => `workspace_id=${encodeURIComponent(ws)}`;
export const listScenes = (ws: string) =>
  api<SceneSummary[]>(`/api/scenes?${query(ws)}`);
export const getScene = (ws: string, id: string) =>
  api<Scene>(`/api/scenes/${id}?${query(ws)}`);
export const createScene = (ws: string, name: string, content: SceneContent) =>
  api<Scene>("/api/scenes", {
    method: "POST",
    body: JSON.stringify({ workspace_id: ws, name, content }),
  });
export const saveScene = (scene: Scene) =>
  api<Scene>(`/api/scenes/${scene.id}`, {
    method: "PATCH",
    body: JSON.stringify({
      workspace_id: scene.workspace_id,
      name: scene.name,
      content: scene.content,
      base_revision: scene.revision,
    }),
  });
/** 导入的 3D 模型归**工作区**,不归某个场景:一件道具导一次,哪个场景都摆得上。 */
export interface SceneModel {
  id: string;
  name: string;
  format: string;
  size: number;
}
export const listSceneModels = (ws: string) =>
  api<SceneModel[]>(`/api/scene-models?${query(ws)}`);
export async function uploadSceneModel(ws: string, file: File) {
  const body = new FormData();
  body.set("workspace_id", ws);
  body.set("file", file);
  return api<SceneModel>(`/api/scene-models`, { method: "POST", body });
}
export const deleteSceneModel = (ws: string, id: string) =>
  api<void>(`/api/scene-models/${id}?${query(ws)}`, { method: "DELETE" });
export async function readSceneModel(
  ws: string,
  id: string,
  signal?: AbortSignal,
) {
  const res = await fetch(`${API_BASE}/api/scene-models/${id}?${query(ws)}`, {
    headers: { Authorization: `Bearer ${getAuthToken()}` },
    signal,
  });
  if (!res.ok) throw new Error(`Model load failed (${res.status})`);
  return res.arrayBuffer();
}

export const deleteScene = (ws: string, id: string) =>
  api<void>(`/api/scenes/${id}?${query(ws)}`, { method: "DELETE" });
