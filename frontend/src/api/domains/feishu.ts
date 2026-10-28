import { api } from "@/api/transport";

/** 飞书机器人(设置 → 飞书机器人)。**接口字面量住在这一层**:界面只调函数(design/apiSeam)。 */

export type FeishuBot = {
  id: string;
  workspace_id: string;
  name: string;
  app_id: string;
  capability: string;
  enabled: boolean;
  status: string;
  status_detail: string;
};

/** 改名称 / 能力档 / 开关 / 凭据。`app_secret` 不给 = 不修改。 */
export function updateFeishuBot(
  botId: string,
  body: { name?: string; app_id?: string; app_secret?: string; capability?: string; enabled?: boolean },
): Promise<FeishuBot> {
  return api<FeishuBot>(`/api/feishu/bots/${botId}`, { method: "PATCH", body: JSON.stringify(body) });
}
