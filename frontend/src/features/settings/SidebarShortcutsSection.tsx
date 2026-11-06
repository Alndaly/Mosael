import React from "react";
import { useQuery } from "@tanstack/react-query";
import { ArrowDown, ArrowUp, Plus, Trash2 } from "lucide-react";

import { listPluginPackages, type PluginPackage } from "@/api/client";
import { errorText } from "@/api/errorMessage";
import { useI18n } from "@/app/preferences";
import { NAV_ITEMS, type StudioView } from "@/components/layout/navLabels";
import {
  setSidebarShortcuts,
  shortcutForComfy,
  shortcutForView,
  shortcutIcon,
  shortcutLabel,
  useSidebarShortcuts,
  type SidebarShortcut,
} from "@/components/layout/sidebarShortcuts";
import { SettingsGroup } from "@/components/settings/settings-layout";
import { Button } from "@/components/ui/button";
import { IconButton } from "@/components/ui/icon-button";
import { SearchableSelect } from "@/components/ui/searchable-select";
import { Truncate } from "@/components/ui/truncate";
import { connectionAddress } from "@/features/plugins/workbench/workbenchAddress";
import { FailureCard, rawFailureFields } from "@/components/failure/FailureCard";

function comfyTargets(packages: readonly PluginPackage[]): SidebarShortcut[] {
  return packages.flatMap((pkg) => {
    if (pkg.id !== "dev.mosael.comfyui") return [];
    return (pkg.instances ?? []).flatMap((instance) => {
      //: 只认连接自己的权威地址。拿不到有效地址时回空,由设置页说明原因;不拿 server_url 兜底,
      //: 免得把一份不完整的配置静默修成看似可用的快捷方式。
      const url = connectionAddress(pkg, instance);
      return url ? [shortcutForComfy(instance.id, instance.name, url)] : [];
    });
  });
}

type PageGroup = { id: StudioView; page: SidebarShortcut };

export function SidebarShortcutsSection() {
  const t = useI18n();
  const shortcuts = useSidebarShortcuts();
  const packages = useQuery({ queryKey: ["plugins"], queryFn: () => listPluginPackages(), retry: false });
  const [page, setPage] = React.useState("");
  const [pluginId, setPluginId] = React.useState("page");
  const [capability, setCapability] = React.useState("comfyui-workbench");
  const [target, setTarget] = React.useState("");
  const groups = React.useMemo<PageGroup[]>(() => NAV_ITEMS
    .filter((item) => item.placement !== "admin" && item.view !== "settings")
    .map((item) => ({ id: item.view, page: shortcutForView(item.view) })), []);
  const group = groups.find((one) => one.id === page);
  const isComfy = page === "plugins" && pluginId === "dev.mosael.comfyui" && capability === "comfyui-workbench";
  const candidates = isComfy && packages.data ? comfyTargets(packages.data) : group ? [group.page] : [];
  const available = candidates.filter((one) => !shortcuts.some((current) => current.id === one.id));
  const selected = candidates.find((one) => one.id === target) ?? candidates[0];
  const chosen = available.find((one) => one.id === target) ?? available[0];
  const alreadyAdded = Boolean(selected && shortcuts.some((one) => one.id === selected.id));

  const pickPage = (view: string) => {
    setPage(view);
    //: 先选插件,再选这个插件提供的能力,最后选连接;工作台仍归在插件下。
    setPluginId(view === "plugins" ? "dev.mosael.comfyui" : "page");
    setCapability("comfyui-workbench");
    const nextGroup = groups.find((one) => one.id === view);
    const options = view === "plugins" && packages.data ? comfyTargets(packages.data) : nextGroup ? [nextGroup.page] : [];
    setTarget(options.find((one) => !shortcuts.some((current) => current.id === one.id))?.id ?? "");
  };
  const pickPlugin = (id: string) => {
    setPluginId(id);
    setCapability("comfyui-workbench");
    const options = id === "dev.mosael.comfyui" && packages.data ? comfyTargets(packages.data) : group ? [group.page] : [];
    setTarget(options.find((one) => !shortcuts.some((current) => current.id === one.id))?.id ?? "");
  };
  const pickCapability = (kind: string) => {
    setCapability(kind);
    const options = kind === "comfyui-workbench" && packages.data ? comfyTargets(packages.data) : group ? [group.page] : [];
    setTarget(options.find((one) => !shortcuts.some((current) => current.id === one.id))?.id ?? "");
  };
  const add = () => {
    if (!chosen) return;
    setSidebarShortcuts([...shortcuts, chosen]);
    const rest = available.filter((one) => one.id !== chosen.id);
    setTarget(rest[0]?.id ?? "");
  };
  const move = (index: number, delta: number) => {
    const nextIndex = index + delta;
    if (nextIndex < 0 || nextIndex >= shortcuts.length) return;
    const next = [...shortcuts];
    [next[index], next[nextIndex]] = [next[nextIndex], next[index]];
    setSidebarShortcuts(next);
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
                            onClick={() => setSidebarShortcuts(shortcuts.filter((one) => one.id !== shortcut.id))}>
                  <Trash2 size={14} />
                </IconButton>
              </div>
            );
          })
        )}
        <div className="flex min-w-0 flex-wrap items-center gap-2 pt-1" data-sidebar-shortcut-picker="">
          <SearchableSelect
            ariaLabel={t("sidebarShortcutsPickPage")}
            value={page}
            onValueChange={pickPage}
            options={groups.map((one) => ({ value: one.id, label: shortcutLabel(one.page, t) }))}
            placeholder={t("sidebarShortcutsPickPage")}
            className="min-w-40 flex-1"
          />
          <SearchableSelect
            ariaLabel={t("sidebarShortcutsPickPlugin")}
            value={pluginId}
            onValueChange={pickPlugin}
            options={[
              { value: "page", label: group ? `${shortcutLabel(group.page, t)}${t("sidebarShortcutsPageSuffix")}` : t("sidebarShortcutsPageItself") },
              ...(packages.data?.filter((pkg) => pkg.id === "dev.mosael.comfyui").map((pkg) => ({ value: pkg.id, label: pkg.name })) ?? []),
            ]}
            placeholder={packages.isPending && page === "plugins" ? t("sidebarShortcutsLoadingPlugins") : t("sidebarShortcutsPickPlugin")}
            disabled={!group || page !== "plugins"}
            className="min-w-40 flex-1"
          />
          <SearchableSelect
            ariaLabel={t("sidebarShortcutsPickCapability")}
            value={capability}
            onValueChange={pickCapability}
            options={[{ value: "comfyui-workbench", label: t("sidebarShortcutsComfyWorkbench") }]}
            placeholder={t("sidebarShortcutsPickCapability")}
            disabled={!isComfy}
            className="min-w-40 flex-1"
          />
          <SearchableSelect
            ariaLabel={t("sidebarShortcutsPickTarget")}
            value={chosen?.id ?? ""}
            onValueChange={setTarget}
            options={available.map((one) => ({ value: one.id, label: shortcutLabel(one, t) }))}
            placeholder={packages.isPending && isComfy ? t("sidebarShortcutsLoadingTargets") : t("sidebarShortcutsPickTarget")}
            disabled={!isComfy}
            className="min-w-48 flex-1"
          />
          <Button variant="outline" disabled={!chosen} onClick={add}>
            <Plus size={13} /> {t("sidebarShortcutsAdd")}
          </Button>
          {alreadyAdded && !chosen && (
            <small className="basis-full text-ui-xs text-muted-foreground">{t("sidebarShortcutsAlreadyAdded")}</small>
          )}
          {!alreadyAdded && !chosen && page === "plugins" && packages.isError && (
            <FailureCard
              size="compact"
              title={t("sidebarShortcutsPluginsError")}
              {...rawFailureFields(errorText(packages.error), t("sidebarShortcutsPluginsError"))}
            />
          )}
          {!alreadyAdded && !chosen && isComfy && !packages.isPending && !packages.isError && (
            <small className="basis-full text-ui-xs text-muted-foreground">{t("sidebarShortcutsNoTargets")}</small>
          )}
        </div>
      </div>
    </SettingsGroup>
  );
}
