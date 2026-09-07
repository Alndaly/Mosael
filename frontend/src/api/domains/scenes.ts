import type { components } from "@/api/generated/schema";
import { api, API_BASE, getAuthToken } from "@/api/transport";
export type Vec3 = [number, number, number];
export type CameraFrame = Required<components["schemas"]["CameraFrame"]>;
export type SceneObject = Omit<
  Required<components["schemas"]["SceneObject"]>,
  "parameters"
> & { parameters: Required<components["schemas"]["ShapeParameters"]> };
export type SceneShot = Omit<
  Required<components["schemas"]["SceneShot"]>,
  "frames"
> & { frames: CameraFrame[] };
export type SceneContent = Omit<
  Required<components["schemas"]["SceneContent"]>,
  "objects" | "shots"
> & { objects: SceneObject[]; shots: SceneShot[] };
export type Scene = Omit<components["schemas"]["SceneOut"], "content"> & {
  content: SceneContent;
};
export type SceneSummary = Pick<
  Scene,
  "id" | "name" | "revision" | "updated_at"
> & { object_count: number; shot_count: number };
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
export async function uploadSceneModel(ws: string, scene: string, file: File) {
  const body = new FormData();
  body.set("workspace_id", ws);
  body.set("file", file);
  return api<{ id: string; name: string; format: string }>(
    `/api/scenes/${scene}/models`,
    { method: "POST", body },
  );
}
export async function readSceneModel(
  ws: string,
  scene: string,
  id: string,
  signal?: AbortSignal,
) {
  const res = await fetch(
    `${API_BASE}/api/scenes/${scene}/models/${id}?${query(ws)}`,
    { headers: { Authorization: `Bearer ${getAuthToken()}` }, signal },
  );
  if (!res.ok) throw new Error(`Model load failed (${res.status})`);
  return res.arrayBuffer();
}

export const deleteScene = (ws: string, id: string) =>
  api<void>(`/api/scenes/${id}?${query(ws)}`, { method: "DELETE" });
