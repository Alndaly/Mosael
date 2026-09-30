import { Badge } from "@/components/ui/badge";
import { useI18n } from "@/app/preferences";
import { cn } from "@/lib/utils";

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

/** 档次 → 语义色调。卡上的后果提示(ConfirmationCard)按同一张表取色,徽标和提示说的是一件事。 */
export type PermissionTone = "danger" | "caution" | "neutral";

/**
 * 最重的色调给**撤不回来**的两档:external 的后果不在这个应用里(公开发布 / 对外写请求 /
 * 本机执行),destroy 的后果在这里但删掉就是删掉了(素材文件、整个项目)。花钱的两档是提醒色;
 * edit 最坏也撤得回,不上色。**不认识的档按最重的算** —— 授权界面上,认不出来不该等于没事。
 */
export function permissionTone(permission: string): PermissionTone {
  if (permission === "edit") return "neutral";
  if (permission === "ai-cost" || permission === "render-cost") return "caution";
  return "danger";
}

//: 浅底 + 同色字,而不是实心色块:此前 external 是一整块粉红实心胶囊,和旁边的主按钮抢眼,
//: 一张卡上最亮的东西成了一个标签。
const TONE_CLASS: Record<PermissionTone, string> = {
  danger:
    "border-[color-mix(in_srgb,var(--destructive)_35%,var(--border))] bg-[color-mix(in_srgb,var(--destructive)_10%,transparent)] text-destructive",
  caution:
    "border-[color-mix(in_srgb,var(--warning)_45%,var(--border))] bg-[color-mix(in_srgb,var(--warning)_12%,transparent)] text-foreground",
  neutral: "border-border bg-secondary text-secondary-foreground",
};

export function PermissionBadge({ permission }: { permission: string }) {
  const t = useI18n();
  const key = LABEL_KEYS[permission as keyof typeof LABEL_KEYS];
  /* 不许换行、不许被挤扁:它和一行可以很长的文字同在一个 flex 行里,两边都可缩时,
     这两个字会被压成一列竖排。 */
  return (
    <Badge
      variant="outline"
      data-tone={permissionTone(permission)}
      className={cn("shrink-0 whitespace-nowrap px-2 text-ui-2xs font-medium", TONE_CLASS[permissionTone(permission)])}
    >
      {key ? t(key) : permission}
    </Badge>
  );
}
