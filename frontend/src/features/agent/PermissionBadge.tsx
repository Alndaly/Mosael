import { Badge } from "@/components/ui/badge";
import { useI18n } from "@/app/preferences";

/**
 * 确认卡上的权限档次徽标 —— 全局确认中心与聊天里的内联卡共用这一个。
 *
 * 之前两处各写了一遍同样的三元表达式,而三元的末尾是**兜底**:后端 TOOL_DEFS 里新增一档
 * 权限,前端不会报错,只会把它显示成「渲染成本」—— 一个撤不回来的动作被标成花钱的动作,
 * 而这行字正是用户点「批准」之前唯一会看的东西。改成查表 + 未知值原样透出,新增档次要么
 * 有对应文案,要么显眼地缺文案,不会伪装成别的档次。
 */
const LABEL_KEYS = {
  edit: "permEdit",
  destroy: "permDestroy",
  "ai-cost": "permAiCost",
  "render-cost": "permRenderCost",
  external: "permExternal",
} as const;

export function PermissionBadge({ permission }: { permission: string }) {
  const t = useI18n();
  const key = LABEL_KEYS[permission as keyof typeof LABEL_KEYS];
  // 最重的样式给**撤不回来**的两档:external 的后果不在这个应用里(公开发布 / 对外写请求 /
  // 本机执行),destroy 的后果在这里但删掉就是删掉了(素材文件、整个项目)。
  const variant =
    permission === "external" || permission === "destroy"
      ? "destructive"
      : permission === "edit"
        ? "secondary"
        : "default";
  /* 不许换行、不许被挤扁:它右邻是一行可以很长的摘要(「3 个工作流编辑: set_node_config,
     set_node_config, set_node_config」),flex 里两边都可缩时,这两个字会被压成一列竖排。 */
  return <Badge variant={variant} className="shrink-0 whitespace-nowrap">{key ? t(key) : permission}</Badge>;
}
