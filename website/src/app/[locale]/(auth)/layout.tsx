import { notFound } from "next/navigation";

import { isLocale } from "@/i18n/config";

/**
 * 账号页外壳:登录 / 注册 / 账号三页共用。
 *
 * 这里**刻意不渲染站头**。人还没进站,顶部先摆一条「产品 / 社区 / 更新日志 / 文档」,注意力
 * 在注册之前就被导走了。品牌字标、Cloud 标识、安全说明和「返回 mosael.com」都在页面自己的
 * AccountShell 里,不靠站头兜底。
 *
 * 这个意图由目录结构表达 —— 账号页住在 `(auth)`,站内页面住在 `(site)` —— 而不是在页面里
 * 通过路径条件隐藏 header。分组名带括号,URL 仍是 `/zh/login`、`/en/signup`、`/zh/account`。
 */
export default async function AuthLayout({
  children,
  params,
}: {
  children: React.ReactNode;
  params: Promise<{ locale: string }>;
}) {
  const { locale } = await params;
  // 动态段什么字符串都收得下,`/fr/login` 不该渲染出一个中文页来。
  if (!isLocale(locale)) notFound();

  return <main id="main">{children}</main>;
}
