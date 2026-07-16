import * as React from "react";
import * as SliderPrimitive from "@radix-ui/react-slider";

import { cn } from "@/lib/utils";

/** 全平面滑杆:2px 轨道 + 12px 圆点,值域样式与旧 range 一致。 */
function Slider({ className, ...props }: React.ComponentProps<typeof SliderPrimitive.Root>) {
  return (
    <SliderPrimitive.Root
      className={cn("relative flex h-5 w-full touch-none select-none items-center", className)}
      {...props}
    >
      {/* 轨道/滑块颜色可被使用方用 --slider-track / --slider-range / --slider-thumb 覆盖
          (监视器的暗色播放条需要白色系轨道)。 */}
      <SliderPrimitive.Track className="relative h-[3px] w-full grow overflow-hidden rounded-full bg-[var(--slider-track,var(--secondary))]">
        <SliderPrimitive.Range className="absolute h-full bg-[var(--slider-range,color-mix(in_srgb,var(--primary)_60%,transparent))]" />
      </SliderPrimitive.Track>
      {(props.value ?? props.defaultValue ?? [0]).map((_, index) => (
        <SliderPrimitive.Thumb
          key={index}
          className="block size-3 rounded-full border border-border-strong bg-[var(--slider-thumb,var(--panel))] outline-none transition-colors hover:border-primary focus-visible:border-primary"
        />
      ))}
    </SliderPrimitive.Root>
  );
}

export { Slider };
