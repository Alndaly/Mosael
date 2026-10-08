import type { components } from "@/api/generated/schema";
import { api, API_BASE, apiBlob, getAuthToken } from "@/api/transport";
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
> & { object_count: number; shot_count: number; preview?: ScenePreviewData; template?: SceneContent["template"] };
const query = (ws: string) => `workspace_id=${encodeURIComponent(ws)}`;
export const listScenes = (ws: string) =>
  api<SceneSummary[]>(`/api/scenes?${query(ws)}`);
export const getScene = (ws: string, id: string) =>
  api<Scene>(`/api/scenes/${id}?${query(ws)}`);
/** 画板 3D 场景格上的全景白模(后端渲)。`<img>` 带不了请求头,凭据走查询参数;带上修订号,场景一改地址就变。 */
export function scenePreviewUrl(ws: string, id: string, revision: number): string {
  const token = getAuthToken();
  const query = new URLSearchParams({ workspace_id: ws, revision: String(revision), ...(token ? { token } : {}) });
  return `${API_BASE}/api/scenes/${encodeURIComponent(id)}/preview?${query}`;
}

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
export async function readSceneModel(ws: string, id: string, signal?: AbortSignal) {
  return (await apiBlob(`/api/scene-models/${id}?${query(ws)}`, { signal })).arrayBuffer();
}

export const deleteScene = (ws: string, id: string) =>
  api<void>(`/api/scenes/${id}?${query(ws)}`, { method: "DELETE" });

// ── 与 Blender 往返 ────────────────────────────────────────────────────────────
// 后端这几条路由没声明响应模型(生成的 schema 里是 unknown),形状在这里写一次,两个面板共用。

export type BlenderConnections = {
  local: boolean;
  connections: { id: string; name: string; enabled: boolean }[];
};
/** 一次「发给 Blender」:就绪之后可以接回来,接回来之后 `received_scene_id` 指向落下的那个场景。 */
export type BlenderTransfer = {
  id: string;
  instance_id: string;
  status: string;
  source_revision: number;
  scene_name: string | null;
  created_at: string;
  received_scene_id: string | null;
  warnings: string[] | null;
  error: string | null;
};
type SceneRef = Pick<Scene, "id" | "workspace_id">;
const blender = (scene: SceneRef) => `/api/scenes/${scene.id}/blender`;

export const listBlenderConnections = () => api<BlenderConnections>("/api/scenes/blender/connections");
export const checkBlenderConnection = (instanceId: string) =>
  api<{ name: string }>(`/api/scenes/blender/connections/${instanceId}/check`, { method: "POST" });
/** 把 Blender 里当前打开的那个场景取回来,存成这个工作区里的一个新场景。 */
export const pullFromBlender = (ws: string, instanceId: string) =>
  api<{ scene_id: string; name: string; warnings: string[] }>(
    `/api/scenes/blender/pull?${query(ws)}&instance_id=${encodeURIComponent(instanceId)}`,
    { method: "POST" },
  );

export const listBlenderTransfers = (scene: SceneRef) =>
  api<BlenderTransfer[]>(`${blender(scene)}?${query(scene.workspace_id)}`);
/** 发的是**已经落库的**那个修订:GLB 由后端按它生成,不需要有人开着这个页面。 */
export const sendToBlender = (scene: SceneRef, body: { instance_id: string; revision: number; shot_id: string }) =>
  api<BlenderTransfer>(blender(scene), {
    method: "POST",
    body: JSON.stringify({ workspace_id: scene.workspace_id, ...body }),
  });
/** 接回到当前场景上:只把内容交回来,由调用方当成一次普通改动写下去(可撤销)。 */
export const receiveIntoScene = (scene: SceneRef, transferId: string) =>
  api<BlenderTransfer & { content: SceneContent }>(
    `${blender(scene)}/${transferId}/receive?${query(scene.workspace_id)}&into_current=true`,
    { method: "POST" },
  );
/** 接回来另存为一个新场景。 */
export const receiveAsNewScene = (scene: SceneRef, transferId: string) =>
  api<BlenderTransfer>(`${blender(scene)}/${transferId}/receive?${query(scene.workspace_id)}`, { method: "POST" });
/** 这次传输在 Blender 那边的工程文件(.blend)。 */
export const downloadBlenderProject = (scene: SceneRef, transferId: string) =>
  apiBlob(`${blender(scene)}/${transferId}/project?${query(scene.workspace_id)}`);
