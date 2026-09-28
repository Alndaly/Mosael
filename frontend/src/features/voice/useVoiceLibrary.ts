import { useQuery } from "@tanstack/react-query";

import { listVoices } from "@/api/client";
import { voiceKeys } from "@/api/queryKeys";

/**
 * 这个工作区的音色库(克隆出来的那些声音)。配音面板、画板的音频卡、设置 → 声音克隆读的都是它;
 * 新建 / 改名 / 删除之后按 `voiceKeys.all(工作区)` 失效。
 *
 * `enabled` 给只在选了「本地克隆」时才用得上音色库的调用方(画板音频卡):没选就不去取。
 */
export function useVoiceLibrary(workspaceId: string, { enabled = true }: { enabled?: boolean } = {}) {
  return useQuery({ queryKey: voiceKeys.all(workspaceId), queryFn: () => listVoices(workspaceId), enabled });
}
