/** 管理页的几个 tab。单独一个轻文件:设置搜索、⌘K 要指到某个 tab,不必为此把整个管理页拉进首屏。 */
export const ADMIN_TABS = ["overview", "members", "pricing", "engines", "deployment"] as const;
export type AdminTab = (typeof ADMIN_TABS)[number];
