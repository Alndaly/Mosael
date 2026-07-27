/**
 * Open Studio 品牌标记:节点式「M」(五个节点连成 M,呼应工作流身份)。
 * 用 currentColor 上色,可放进任意底色的容器(侧栏品牌方块 = 白色描边)。
 * viewBox 已裁到标记边界,小尺寸也填得满。
 */
export function BrandMark({ size = 22, className }: { size?: number; className?: string }) {
  return (
    <svg width={size} height={size} viewBox="22 26 76 72" fill="none" className={className} aria-hidden="true">
      <path
        d="M34 86 L34 38 L60 62 L86 38 L86 86"
        stroke="currentColor"
        strokeWidth="9"
        strokeLinejoin="round"
        strokeLinecap="round"
        opacity="0.5"
      />
      <g fill="currentColor">
        <circle cx="34" cy="38" r="10" />
        <circle cx="60" cy="62" r="10" />
        <circle cx="86" cy="38" r="10" />
        <circle cx="34" cy="86" r="10" />
        <circle cx="86" cy="86" r="10" />
      </g>
    </svg>
  );
}
