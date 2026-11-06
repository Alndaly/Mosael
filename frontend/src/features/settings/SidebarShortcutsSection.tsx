import React from "react";
import { useQuery } from "@tanstack/react-query";
import { ArrowDown, ArrowUp, Plus, Trash2 } from "lucide-react";

import { listPluginPackages, type PluginPackage } from "@/api/client";
import { useI18n } from "@/app/preferences";
import { NAV_ITEMS } from "@/components/layout/navLabels";
import {
  setSidebarShortcuts,
  shortcutForComfy,
  shortcutForView,
  shortcutIcon,
  shortcutLabel,
  useSidebarShortcuts,
  type SidebarShortcut,
} from "@/components/layout/sidebarShortcuts";
import { connectionAddress } from "@/features/plugins/workbench/workbenchAddress";
import { SettingsGroup } from "@/components/settings/settings-layout";
import { Button } from "@/components/ui/button";
import { IconButton } from "@/components/ui/icon-button";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Truncate } from "@/components/ui/truncate";

/**
 * 设置 → 侧栏快捷方式。
 *
 * 候选只来自两处:页面清单(和导航同一份 `NAV_ITEMS`)和 ComfyUI 连接的「工作台」。不让人手填 URL ——
 * 快捷方式要能在这个工作区里打开一个东西,不是一张书签。排序就是侧栏上从左到右的顺序。
 */
function comfyCandidates(packages: readonly PluginPackage[]): SidebarShortcut[] {
  return packages.flatMap((pkg) => {
    if (pkg.id !== "dev.mosael.comfyui") return [];
    return (pkg.instances ?? []).flatMap((instance) => {
      const url = connectionAddress(pkg, instance);
      return url ? [shortcutForComfy(instance.id, instance.name, url)] : [];
    });
  });
}

export function SidebarShortcutsSection() {
  const t = useI18n();
  const shortcuts = useSidebarShortcuts();
  const packages = useQuery({ queryKey: ["plugins"], queryFn: () => listPluginPackages(), retry: false });
  const [picked, setPicked] = React.useState("");
  const candidates = React.useMemo(() => {
    const views = NAV_ITEMS
      .filter((item) => item.placement !== "admin" && item.view !== "settings")
      .map((item) => shortcutForView(item.view));
    //: 插件能力放在页面之前 —— 「ComfyUI 工作台」是这项功能最想要的那一类,别让它埋在页面清单底下。
    return [...(packages.data ? comfyCandidates(packages.data) : []), ...views];
  }, [packages.data]);
  const available = candidates.filter((one) => !shortcuts.some((current) => current.id === one.id));

  const commit = (next: readonly SidebarShortcut[]) => setSidebarShortcuts(next);
  const add = () => {
    const candidate = candidates.find((one) => one.id === picked);
    if (!candidate) return;
    commit([...shortcuts, candidate]);
    setPicked("");
  };
  const move = (index: number, delta: number) => {
    const target = index + delta;
    if (target < 0 || target >= shortcuts.length) return;
    const next = [...shortcuts];
    [next[index], next[target]] = [next[target], next[index]];
    commit(next);
  };

  return (
    <SettingsGroup title={t("sidebarShortcutsTitle")} description={t("sidebarShortcutsDesc")}>
      <div className="grid gap-2 py-4">
        {shortcuts.length === 0 ? (
          <p className="m-0 text-ui-sm text-muted-foreground">{t("sidebarShortcutsEmpty")}</p>
        ) : (
          shortcuts.map((shortcut, index) => {
            const Icon = shortcutIcon(shortcut);
            const label = shortcutLabel(shortcut, t);
            return (
              <div
                key={shortcut.id}
                data-sidebar-shortcut-row=""
                className="flex min-w-0 items-center gap-2 rounded-lg border border-border bg-panel-subtle px-3 py-2"
              >
                <span className="grid size-8 shrink-0 place-items-center rounded-md bg-secondary text-muted-foreground">
                  <Icon size={15} />
                </span>
                <Truncate className="min-w-0 flex-1 text-ui-sm text-foreground">{label}</Truncate>
                <IconButton size="icon-sm" label={t("sidebarShortcutsUp").replace("{name}", label)} disabled={index === 0}
                            onClick={() => move(index, -1)}>
                  <ArrowUp size={14} />
                </IconButton>
                <IconButton size="icon-sm" label={t("sidebarShortcutsDown").replace("{name}", label)} disabled={index === shortcuts.length - 1}
                            onClick={() => move(index, 1)}>
                  <ArrowDown size={14} />
                </IconButton>
                <IconButton size="icon-sm" label={t("sidebarShortcutsRemove").replace("{name}", label)}
                            onClick={() => commit(shortcuts.filter((one) => one.id !== shortcut.id))}>
                  <Trash2 size={14} />
                </IconButton>
              </div>
            );
          })
        )}
        <div className="flex min-w-0 flex-wrap items-center gap-2 pt-1">
          <Select value={picked} onValueChange={setPicked}>
            <SelectTrigger className="min-w-52 flex-1" aria-label={t("sidebarShortcutsPick")}>
              <SelectValue placeholder={t("sidebarShortcutsPick")} />
            </SelectTrigger>
            <SelectContent>
              {available.map((candidate) => (
                <SelectItem key={candidate.id} value={candidate.id}>
                  {shortcutLabel(candidate, t)}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <Button variant="outline" disabled={!picked} onClick={add}>
            <Plus size={13} /> {t("sidebarShortcutsAdd")}
          </Button>
        </div>
      </div>
    </SettingsGroup>
  );
}
