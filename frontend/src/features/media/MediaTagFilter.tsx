import React from "react";
import { Check, ChevronDown, Tags, X } from "lucide-react";
import { useI18n } from "@/app/preferences";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { cn } from "@/lib/utils";

/** Keep a growing tag library out of the asset toolbar; retain one active filter. */
export function MediaTagFilter({ tags, value, onChange }: {
  tags: string[]; value: string | null; onChange: (value: string | null) => void;
}) {
  const t = useI18n();
  const [open, setOpen] = React.useState(false);
  const [search, setSearch] = React.useState("");
  const matches = tags.filter(tag => tag.toLocaleLowerCase().includes(search.trim().toLocaleLowerCase()));
  return <div className="flex min-w-0 items-center gap-1">
    <Popover open={open} onOpenChange={next => { setOpen(next); setSearch(""); }}>
      <PopoverTrigger asChild>
        <Button variant="outline" aria-label={t("filterByTag")} className={cn("max-w-52", value && "border-primary/40 bg-accent text-primary")}>
          <Tags /><span className="truncate">{value || t("filterByTag")}</span><ChevronDown />
        </Button>
      </PopoverTrigger>
      <PopoverContent align="end" className="w-64 p-2">
        <Input aria-label={t("mediaSearchTags")} placeholder={t("mediaSearchTags")} value={search} onChange={event => setSearch(event.target.value)} />
        <div className="mt-2 grid max-h-64 gap-1 overflow-y-auto" role="group" aria-label={t("filterByTag")}>
          {matches.map(tag => <Button key={tag} variant="ghost" className="min-w-0 justify-start" aria-pressed={tag === value} onClick={() => { onChange(tag === value ? null : tag); setOpen(false); setSearch(""); }}>
            <span className="min-w-0 flex-1 truncate">{tag}</span>{tag === value && <Check />}
          </Button>)}
          {matches.length === 0 && <p className="m-0 px-3 py-4 text-ui-sm text-muted-foreground">{t("studioNoMatches")}</p>}
        </div>
      </PopoverContent>
    </Popover>
    {value && <Button variant="outline" className="px-3" aria-label={t("mediaClearTag")} onClick={() => onChange(null)}><X /></Button>}
  </div>;
}
