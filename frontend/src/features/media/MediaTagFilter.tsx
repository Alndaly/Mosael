import React from "react";
import { Check, ChevronDown, Tags, X } from "lucide-react";
import { useI18n } from "@/app/preferences";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { cn } from "@/lib/utils";
import { TAG_MATCHES, type TagMatch } from "./assetTags";

/**
 * 按标签筛选素材 —— **可以同时勾几个**。素材库和剪辑页的素材面板共用这一个。
 *
 * 此前只能选一个:点一个标签弹层就关,再点另一个就换掉前一个。而按标签找素材的常见问法是
 * 「既是『海边』又是『黄昏』的」或者「『访谈』和『口播』都要」—— 两种都要能表达,所以弹层
 * 底部有一个切换:同时有这些标签(越勾越窄,默认)/ 有其中任一(越勾越宽)。
 *
 * 弹层在勾选时不关,连着勾几个不用反复打开。标签库会越长越多,所以列表可搜索;每个标签后面
 * 标着挂了几条素材,勾之前就知道会剩多少。
 *
 * 触发器两种长相,弹层是同一个:
 * - 默认:带字的按钮,写着勾了哪个(几个就「第一个 +N」),右边一颗清空键。素材库的筛选条够宽。
 * - `compact`:只有图标,勾了几个就在角上标几 —— 剪辑页素材面板窄,放不下字。勾了哪些、怎么
 *   去掉,由面板在搜索框下面摆一排 {@link ActiveTagChips} 来说。
 */
export function MediaTagFilter({ counts, value, onChange, match, onMatchChange, compact = false }: {
  /** 标签 → 挂了几条素材;键的顺序就是列出来的顺序(见 `tagCounts`)。 */
  counts: ReadonlyMap<string, number>;
  value: string[];
  onChange: (value: string[]) => void;
  match: TagMatch;
  onMatchChange: (match: TagMatch) => void;
  compact?: boolean;
}) {
  const t = useI18n();
  const [open, setOpen] = React.useState(false);
  const [search, setSearch] = React.useState("");
  const query = search.trim().toLocaleLowerCase();
  const matches = [...counts.keys()].filter(tag => tag.toLocaleLowerCase().includes(query));
  const chosen = new Set(value);
  const toggle = (tag: string) => onChange(chosen.has(tag) ? value.filter(one => one !== tag) : [...value, tag]);
  // 按钮上:一个就写它;几个就写第一个 + 「+N」,完整的在弹层里看。
  const label = value.length === 0 ? t("filterByTag") : value.length === 1 ? value[0] : `${value[0]} +${value.length - 1}`;
  const active = value.length > 0;
  const trigger = compact ? (
    <Button variant="ghost" size="icon-sm" aria-label={t("filterByTag")} title={active ? label : t("filterByTag")} className={cn("relative shrink-0 text-muted-foreground hover:text-foreground", active && "bg-accent text-primary hover:text-primary")}>
      <Tags />
      {active && <span data-tag-filter-count className="absolute -right-1 -top-1 grid h-4 min-w-4 place-items-center rounded-full bg-primary px-1 text-ui-2xs leading-4 tabular-nums text-primary-foreground">{value.length}</span>}
    </Button>
  ) : (
    <Button variant="outline" aria-label={t("filterByTag")} className={cn("max-w-52", active && "border-primary/40 bg-accent text-primary")}>
      <Tags /><span className="truncate">{label}</span><ChevronDown />
    </Button>
  );
  return <div className="flex min-w-0 items-center gap-1">
    <Popover open={open} onOpenChange={next => { setOpen(next); setSearch(""); }}>
      <PopoverTrigger asChild>{trigger}</PopoverTrigger>
      <PopoverContent align="end" className="w-64 p-2">
        <Input aria-label={t("mediaSearchTags")} placeholder={t("mediaSearchTags")} value={search} onChange={event => setSearch(event.target.value)} />
        <div className="mt-2 grid max-h-64 gap-1 overflow-y-auto" role="group" aria-label={t("filterByTag")}>
          {matches.map(tag => <Button key={tag} variant="ghost" className={cn("min-w-0 justify-start", chosen.has(tag) && "text-primary hover:text-primary")} aria-pressed={chosen.has(tag)} onClick={() => toggle(tag)}>
            <span className="min-w-0 flex-1 truncate text-left">{tag}</span>
            <span className="shrink-0 text-ui-xs tabular-nums text-muted-foreground">{counts.get(tag)}</span>
            {/* 勾没勾都占一格,数字才不会随着勾选左右跳。 */}
            <Check className={cn("shrink-0", !chosen.has(tag) && "invisible")} />
          </Button>)}
          {matches.length === 0 && <p className="m-0 px-3 py-4 text-ui-sm text-muted-foreground">{t("studioNoMatches")}</p>}
        </div>
        {/* 勾了两个以上才有「同时 / 任一」之分。 */}
        {value.length > 1 && (
          <div className="mt-2 grid grid-cols-2 gap-1 border-t border-divider pt-2" role="radiogroup" aria-label={t("mediaTagMatch")}>
            {TAG_MATCHES.map(mode => (
              <Button key={mode} variant={match === mode ? "secondary" : "ghost"} size="sm" role="radio" aria-checked={match === mode} onClick={() => onMatchChange(mode)}>
                {t(mode === "all" ? "mediaTagMatchAll" : "mediaTagMatchAny")}
              </Button>
            ))}
          </div>
        )}
      </PopoverContent>
    </Popover>
    {!compact && active && <Button variant="outline" className="px-3" aria-label={t("mediaClearTag")} onClick={() => onChange([])}><X /></Button>}
  </div>;
}

/**
 * 勾着的标签摆成一排,每个点一下就去掉;两个以上时写明是「同时带有」还是「带有任一」,
 * 末尾一键清空。给 `compact` 的 {@link MediaTagFilter} 配套 —— 图标上的数字只说勾了几个,
 * 这一排说勾了哪些。
 */
export function ActiveTagChips({ value, onChange, match }: {
  value: string[];
  onChange: (value: string[]) => void;
  match: TagMatch;
}) {
  const t = useI18n();
  if (value.length === 0) return null;
  return (
    <div className="flex min-w-0 flex-wrap items-center gap-1" role="group" aria-label={t("mediaActiveTags")}>
      {value.length > 1 && <span className="text-ui-2xs text-muted-foreground">{t(match === "all" ? "mediaTagMatchAll" : "mediaTagMatchAny")}</span>}
      {value.map(tag => (
        <button
          key={tag}
          type="button"
          aria-label={t("mediaRemoveTag").replace("{tag}", tag)}
          title={t("mediaRemoveTag").replace("{tag}", tag)}
          onClick={() => onChange(value.filter(one => one !== tag))}
          className="inline-flex h-6 min-w-0 max-w-full cursor-pointer items-center gap-1 rounded-sm bg-accent pl-2 pr-1 text-ui-xs text-primary hover:bg-[color-mix(in_srgb,var(--primary)_16%,transparent)]"
        >
          <span className="min-w-0 truncate">{tag}</span>
          <X size={12} className="shrink-0" />
        </button>
      ))}
      <button type="button" aria-label={t("mediaClearTag")} onClick={() => onChange([])} className="inline-flex h-6 cursor-pointer items-center rounded-sm px-1.5 text-ui-xs text-muted-foreground hover:bg-secondary hover:text-foreground">
        {t("mediaClearTagShort")}
      </button>
    </div>
  );
}
