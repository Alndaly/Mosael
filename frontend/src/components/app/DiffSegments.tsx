import type { DiffSegment } from "@/lib/textDiff";

/**
 * 一段差异的字:删去的划掉(淡红底),新加的高亮(淡绿底),没变的照常。
 *
 * 改笔记确认卡上的「原文 → 新文」和笔记版本记录里的对比用的是同一套,读起来是同一种东西。只画字,
 * 外面那一层(段落、折叠、边框)由用的地方给。`quietSame`:没变的字压成淡色(卡上只想让人看改了什么)。
 */
export function DiffSegments({ segments, quietSame = false }: { segments: DiffSegment[]; quietSame?: boolean }) {
  return (
    <>
      {segments.map((one, index) =>
        one.kind === "del" ? (
          <del key={index} className="rounded-sm bg-[color-mix(in_srgb,var(--destructive)_12%,transparent)] text-destructive line-through">
            {one.text}
          </del>
        ) : one.kind === "ins" ? (
          <ins key={index} className="rounded-sm bg-[color-mix(in_srgb,var(--success)_16%,transparent)] text-foreground no-underline">
            {one.text}
          </ins>
        ) : (
          <span key={index} className={quietSame ? "text-muted-foreground" : undefined}>{one.text}</span>
        ),
      )}
    </>
  );
}
