import { splitByQuery } from "@/lib/highlight";
import { cn } from "@/lib/utils";

/**
 * 搜索结果里标出命中的那几个字。
 *
 * 用 `<mark>` 而不是 `<span>`:它本来就是"标出来"的语义,读屏会读成强调,而不是一段
 * 莫名其妙加粗的文字。默认底色在这里是多余的(结果行本身已经有选中态),所以只留字重和颜色。
 */
export function Highlight({ text, query, className }: { text: string; query: string; className?: string }) {
  const parts = splitByQuery(text, query);
  return (
    <span className={className}>
      {parts.map((part, index) =>
        part.match ? (
          <mark key={index} className={cn("bg-transparent font-semibold text-primary")}>
            {part.text}
          </mark>
        ) : (
          part.text
        ),
      )}
    </span>
  );
}
