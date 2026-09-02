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
      <img
        src={`${brandBase}/mosael-icon-light.png`}
        alt=""
        draggable={false}
        className="block h-full w-full object-contain dark:hidden"
      />
      <img
        src={`${brandBase}/mosael-icon-dark.png`}
        alt=""
        draggable={false}
        className="hidden h-full w-full object-contain dark:block"
      />
    </span>
  );
}
