import type { MessageKey } from "@/app/messages";

type Translate = (key: MessageKey) => string;

/**
 * 一条插件权限(`network:oss`、`process:spawn`…)**用人话说是什么**。
 *
 * 权限码是给机器对账的,决定装不装的人读不出 `filesystem:write` 意味着什么。这里把认得的几类
 * 翻成一句话,码本身仍在旁边小字留着 —— 那是和插件作者、和权限设置页对得上的唯一凭据。
 * 认不出的(作者自己发明的类别)返回 null,界面只显示码:**不猜**。
 */
export function describePermission(t: Translate, permission: string): string | null {
  const [kind, ...rest] = permission.split(":");
  const scope = rest.join(":");
  switch (kind) {
    case "network":
      if (scope === "localhost") return t("pluginPermNetworkLocal");
      return t("pluginPermNetwork").replace("{scope}", scope || permission);
    case "process":
      return t("pluginPermProcess");
    case "filesystem":
      if (scope === "read") return t("pluginPermFsRead");
      if (scope === "write") return t("pluginPermFsWrite");
      return null;
    default:
      return null;
  }
}

/** 插件能替 Mosael 做的一类事(清单里的 `provides`)。认不出的返回 null,界面显示原词。 */
export function describeProvides(t: Translate, capability: string): string | null {
  if (capability === "public_url") return t("pluginProvidesPublicUrl");
  return null;
}
