import React from "react";
import { useQuery, useQueryClient, type QueryClient } from "@tanstack/react-query";

import { listConfirmations, type Confirmation } from "@/api/client";
import { confirmationKeys } from "@/api/queryKeys";
import { invalidateResources } from "@/api/resourceKeys";

/** 拍板之后会动缓存的那几样:卡的状态,和它声明改了哪几种数据。 */
type DecidedCard = Pick<Confirmation, "status" | "writes">;

/**
 * 一张(或几张)确认卡拍板之后要刷新的缓存。
 *
 * **改了什么由卡自己说**(`writes`,后端 ConfirmableTool.writes,ADR 0053),换成缓存键的表在 api/resourceKeys,和任务
 * 做完时同一张。此前这里是一份按工具逐行手写的清单,每加一种会直接改数据的卡就得记得来补一行 —— 漏过项目(在剪辑页里
 * 批掉「删除项目 X」,切换器还列着 X)、发布任务;拒掉的卡也照着整份清单刷一遍。
 *
 * - 卡本身(待批的、留痕的、执行完的)每次都刷;
 * - 拒掉、作废、还在等的卡什么都没做,只刷卡;执行完的、执行失败的(可能做了一半)按它声明的刷;
 * - 只建后台任务的卡(生成、转换、导入、渲染)声明里不含任务的产出:那些由任务做完时按目录的 `affects` 刷(components/jobs)。
 */
export function invalidateAfterDecision(qc: QueryClient, workspaceId: string, cards: DecidedCard | readonly DecidedCard[]): void {
  void qc.invalidateQueries({ queryKey: confirmationKeys.all(workspaceId) });
  const ran = (Array.isArray(cards) ? cards : [cards]).filter((card) => card.status === "executed" || card.status === "failed");
  invalidateResources(qc, ran.flatMap((card) => card.writes ?? []));
}

/** 看最近多少张执行完的卡。一次轮询之间落地的卡不会比这更多;多了也只是少刷一次,不会刷错。 */
const LANDED_WINDOW = 20;

/**
 * **不是这个界面批的卡**,执行落地之后这边也要刷新。
 *
 * `invalidateAfterDecision` 只挂在这个界面自己的「批准」按钮上,而卡还有别的批法:自动放行(「本会话始终允许」、
 * auto / bypass 档)在后端线程里批,飞书卡片在手机上批,另一台设备在它自己的界面里批。那些卡执行完了,这边
 * 没有任何一处知道 —— 用户反馈过:智能体删了两个素材,工具结果写着「2 个素材已删除」,素材库里两个都还在。
 * 库里确实删了(后端每个入口都提交,见 backend/tests/test_card_approval_lands),是素材库那份缓存没人让它过期:
 * 全局 staleTime 60 秒、不在获焦时重拉,开着的素材库页就一直是旧的。
 *
 * 所以这里不管是谁批的,只看「这个工作区里有没有新执行完的卡」:有,就按那几张卡各自声明改了的数据刷一遍。挂在应用级,
 * 聊天面板收着、人在别的页面时同样生效。首次取到的那批不算 —— 那是打开应用之前就落地的,缓存本来就是新取的。
 */
export function useRefreshWhenCardsLand(workspaceId: string): void {
  const qc = useQueryClient();
  const landed = useQuery({
    queryKey: confirmationKeys.executed(workspaceId),
    queryFn: () => listConfirmations({ workspaceId, status: "executed", limit: LANDED_WINDOW }),
    // **轮询,而且只在窗口看得见时。** 仓库里没有工作区级的推送通道(唯一的 SSE 是某一轮对话的流,只在那一轮
    // 跑着、面板开着时才连),为这一件事开一条长连接不划算。窗口藏起来时停下(`refetchIntervalInBackground`
    // 显式写成 false —— 它是 React Query 的默认,写出来免得哪天被当成可以打开的开关);回到前台当场查一次,
    // 不等下一个三秒(全局关了获焦重拉,这里单独开)。
    refetchInterval: 3000,
    refetchIntervalInBackground: false,
    refetchOnWindowFocus: true,
    staleTime: 0,
  });
  // 按工作区记:切了工作区,另一个工作区的那批不是「新落地的」。
  const seen = React.useRef<{ workspaceId: string; ids: Set<string> } | null>(null);
  React.useEffect(() => {
    if (!landed.data) return;
    const ids = new Set(landed.data.map((card) => card.id));
    const before = seen.current?.workspaceId === workspaceId ? seen.current.ids : null;
    seen.current = { workspaceId, ids };
    const fresh = before ? landed.data.filter((card) => !before.has(card.id)) : [];
    if (fresh.length) invalidateAfterDecision(qc, workspaceId, fresh);
  }, [landed.data, qc, workspaceId]);
}
