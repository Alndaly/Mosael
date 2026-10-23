import { FallbackImage } from "@/components/ui/fallback-image";
type BrandMarkProps = {
  size?: number;
  className?: string;
};

/** Theme-aware Mosael app icon supplied with the brand identity. */
export function BrandMark({ size = 22, className }: BrandMarkProps) {
  const dimensions = { width: size, height: size };
  const brandBase = `${import.meta.env.BASE_URL}brand`;

  return (
    <span className={className} style={dimensions} aria-hidden="true">
      {/* 品牌图标读不出来时画一个字母:比一枚破图图标体面,也仍然认得出这是谁。 */}
      <FallbackImage
        src={`${brandBase}/mosael-icon-light.png`}
        fallback={<span className="grid h-full w-full place-items-center text-[10px] font-bold">M</span>}
        alt=""
        draggable={false}
        className="block h-full w-full object-contain dark:hidden"
      />
      <FallbackImage
        src={`${brandBase}/mosael-icon-dark.png`}
        fallback={<span className="grid h-full w-full place-items-center text-[10px] font-bold">M</span>}
        alt=""
        draggable={false}
        className="hidden h-full w-full object-contain dark:block"
      />
    </span>
  );
}
