import { Loader2 } from "lucide-react";

import { BrandMark } from "@/components/layout/BrandMark";

type StartupLoadingProps = {
  label: string;
  detail: string;
};

/**
 * 应用壳出现之前的阻塞式加载反馈。
 *
 * 品牌标记让这段等待仍然属于 Mosael；外圈只表达「仍在工作」，不伪造无法得知的进度。
 * reduced-motion 由全局动效规则统一降级，即使不旋转，文案和 aria-busy 也仍能说明状态。
 */
export function StartupLoading({ label, detail }: StartupLoadingProps) {
  return (
    <div
      role="status"
      aria-live="polite"
      aria-busy="true"
      className="grid min-w-[260px] justify-items-center gap-5 px-8 py-10 text-center"
    >
      <div className="relative grid size-[72px] place-items-center text-primary" aria-hidden="true">
        <Loader2
          size={72}
          strokeWidth={1.25}
          className="absolute inset-0 animate-mosael-spin opacity-55"
        />
        <BrandMark size={46} className="relative block" />
      </div>

      <div className="grid gap-1.5">
        <p className="m-0 text-ui-md font-semibold text-foreground">{label}</p>
        <p className="m-0 text-ui-xs leading-relaxed text-muted-foreground">{detail}</p>
      </div>
    </div>
  );
}
