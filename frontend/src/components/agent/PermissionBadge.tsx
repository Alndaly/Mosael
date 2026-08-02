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
  "ai-cost": "permAiCost",
  "render-cost": "permRenderCost",
  external: "permExternal",
} as const;

export function PermissionBadge({ permission }: { permission: string }) {
  const t = useI18n();
  const key = LABEL_KEYS[permission as keyof typeof LABEL_KEYS];
  // external:后果不在这个应用里(公开发布 / 对外写请求 / 本机执行),用最重的样式。
  const variant = permission === "external" ? "destructive" : permission === "edit" ? "secondary" : "default";
  return <Badge variant={variant}>{key ? t(key) : permission}</Badge>;
}
