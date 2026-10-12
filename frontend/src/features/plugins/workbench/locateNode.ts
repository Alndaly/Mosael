/**
 * 在画布上定位一个节点(`12`、子图里的 `12:5`,桥先一层层打开):选中它、移到中间。成了回空串,没成回一句给人看的
 * 原因(画布上没有这个节点 / 它在子图里而这版前端进不去 / 桥那边没做成,原话附在后面)。
 *
 * 两处用它,说的是同一件事,所以只有这一份:助手回复里的节点引用(AssistantPanel 的 NodeRef)、「工作流里能填的」
 * 那一列节点分组标题上的 `#节点号`(LocateNodeButton,见 appForm/SourcePanel)。
 *
 * **界面这一侧不一定有画布**:工作流库里那个宽版编辑器旁边就没有,这时桥回的是 `closed` —— 说的是"还没连上画布",
 * 而不是"没做成:closed"(把原因码露在界面上,读的人不知道那是什么;`workbenchAssistantNoCanvas` 本来就是为这件事
 * 写的一句话)。照样不假装定位成了,也不为它去开工作台(那是另一件事)。
 */
import { useI18n } from "@/app/preferences";
import { workbenchCall } from "@/features/plugins/workbench/workbenchSession";

type Translate = ReturnType<typeof useI18n>;

export async function locateNode(t: Translate, node: string): Promise<string> {
  const result = await workbenchCall({ op: "locate", node, subgraph: null });
  if (result.ok) return "";
  return result.error === "noNode" ? t("workbenchAssistantNoNode").replace("{node}", node)
    : result.error === "inSubgraph" ? t("workbenchAssistantInSubgraph")
    //: 还没连上画布(宽版编辑器旁边没有画布就是这种):说这一句,不把原因码 `closed` 摆到人眼前。
    : result.error === "closed" ? t("workbenchAssistantNoCanvas")
    : t("workbenchCallFailed").replace("{why}", "message" in result && result.message ? result.message : result.error);
}
