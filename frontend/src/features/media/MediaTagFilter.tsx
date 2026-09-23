import React from "react";
import { Check, ChevronDown, Tags, X } from "lucide-react";
import { useI18n } from "@/app/preferences";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { cn } from "@/lib/utils";

export type TagMatch = "all" | "any";

/**
 * 按标签筛选素材 —— **可以同时勾几个**。
 *
 * 此前只能选一个:点一个标签弹层就关,再点另一个就换掉前一个。而按标签找素材的常见问法是
 * 「既是『海边』又是『黄昏』的」或者「『访谈』和『口播』都要」—— 两种都要能表达,所以弹层
 * 底部有一个切换:同时有这些标签(越勾越窄,默认)/ 有其中任一(越勾越宽)。
 *
 * 弹层在勾选时不关,连着勾几个不用反复打开。标签库会越长越多,所以列表可搜索。
 */
export function MediaTagFilter({ tags, value, onChange, match, onMatchChange }: {
  tags: string[];
  value: string[];
  onChange: (value: string[]) => void;
  match: TagMatch;
  onMatchChange: (match: TagMatch) => void;
}) {
  const t = useI18n();
  const [open, setOpen] = React.useState(false);
  const [search, setSearch] = React.useState("");
  const matches = tags.filter(tag => tag.toLocaleLowerCase().includes(search.trim().toLocaleLowerCase()));
  const chosen = new Set(value);
  const toggle = (tag: string) => onChange(chosen.has(tag) ? value.filter(one => one !== tag) : [...value, tag]);
  // 按钮上:一个就写它;几个就写第一个 + 「+N」,完整的在弹层里看。
  const label = value.length === 0 ? t("filterByTag") : value.length === 1 ? value[0] : `${value[0]} +${value.length - 1}`;
  return <div className="flex min-w-0 items-center gap-1">
    <Popover open={open} onOpenChange={next => { setOpen(next); setSearch(""); }}>
      <PopoverTrigger asChild>
        <Button variant="outline" aria-label={t("filterByTag")} className={cn("max-w-52", value.length > 0 && "border-primary/40 bg-accent text-primary")}>
          <Tags /><span className="truncate">{label}</span><ChevronDown />
        </Button>
      </PopoverTrigger>
      <PopoverContent align="end" className="w-64 p-2">
        <Input aria-label={t("mediaSearchTags")} placeholder={t("mediaSearchTags")} value={search} onChange={event => setSearch(event.target.value)} />
        <div className="mt-2 grid max-h-64 gap-1 overflow-y-auto" role="group" aria-label={t("filterByTag")}>
          {matches.map(tag => <Button key={tag} variant="ghost" className="min-w-0 justify-start" aria-pressed={chosen.has(tag)} onClick={() => toggle(tag)}>
            <span className="min-w-0 flex-1 truncate text-left">{tag}</span>{chosen.has(tag) && <Check />}
          </Button>)}
          {matches.length === 0 && <p className="m-0 px-3 py-4 text-ui-sm text-muted-foreground">{t("studioNoMatches")}</p>}
        </div>
        {/* 勾了两个以上才有「同时 / 任一」之分。 */}
        {value.length > 1 && (
          <div className="mt-2 grid grid-cols-2 gap-1 border-t border-divider pt-2" role="radiogroup" aria-label={t("mediaTagMatch")}>
            {(["all", "any"] as const).map(mode => (
              <Button key={mode} variant={match === mode ? "secondary" : "ghost"} size="sm" role="radio" aria-checked={match === mode} onClick={() => onMatchChange(mode)}>
                {t(mode === "all" ? "mediaTagMatchAll" : "mediaTagMatchAny")}
              </Button>
            ))}
          </div>
        )}
      </PopoverContent>
    </Popover>
    {value.length > 0 && <Button variant="outline" className="px-3" aria-label={t("mediaClearTag")} onClick={() => onChange([])}><X /></Button>}
  </div>;
}
