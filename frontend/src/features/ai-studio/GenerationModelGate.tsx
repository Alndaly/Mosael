import { Settings2 } from "lucide-react";

import { useI18n } from "@/app/preferences";
import { Button } from "@/components/ui/button";
import { gotoSettings } from "@/lib/deepLink";

/**
 * 生成区的无模型出口。
 *
 * 生成模型列表为空时，继续留一个禁用发送键只会让人猜发生了什么；这里把同一块位置
 * 换成明确的设置入口，并直达图像生成供应商。配置完成后查询刷新，正常模型标签会回来。
 */
export function GenerationModelGate({ hasModel, loading }: { hasModel: boolean; loading: boolean }) {
  const t = useI18n();
  if (hasModel || loading) return null;

  return (
    <Button
      type="button"
      variant="outline"
      size="sm"
      className="h-7 gap-1 rounded-full px-2.5 text-xs text-muted-foreground hover:text-foreground"
      onClick={() => gotoSettings("providers:image")}
    >
      <Settings2 size={13} />
      {t("generationConfigureModel")}
    </Button>
  );
}
