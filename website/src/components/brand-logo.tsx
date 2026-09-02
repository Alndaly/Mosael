import Image from "next/image";

import { cn } from "@/lib/utils";

export function BrandIcon({ size = 32, className }: { size?: number; className?: string }) {
  return (
    <span className={cn("relative block shrink-0", className)} style={{ width: size, height: size }} aria-hidden="true">
      <Image src="/brand/mosael-icon-light.png" alt="" fill sizes={`${size}px`} unoptimized className="object-contain dark:hidden" />
      <Image src="/brand/mosael-icon-dark.png" alt="" fill sizes={`${size}px`} unoptimized className="hidden object-contain dark:block" />
    </span>
  );
}

export function BrandWordmark({ className, priority = false }: { className?: string; priority?: boolean }) {
  return (
    <Image
      src="/brand/mosael-wordmark.png"
      alt="Mosael"
      width={1086}
      height={362}
      priority={priority}
      unoptimized
      className={cn("h-auto object-contain", className)}
    />
  );
}
