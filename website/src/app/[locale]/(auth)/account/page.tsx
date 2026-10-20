import { notFound, permanentRedirect } from "next/navigation";

import { parseOAuthOutcome } from "@/components/account/dashboard-utils";
import { isLocale } from "@/i18n/config";

type Params = Promise<{ locale: string }>;
type SearchParams = Promise<{ oauth?: string | string[] }>;

/**
 * `/account` 已经并进控制台(`/[locale]/dashboard`):这一页只剩下一个跳转。
 *
 * **为什么是永久(308)而不是临时(307)**:账号页不是「临时挪开」,而是被收起来了 ——
 * 页脚、站头头像、登录后的去处全都已经指向控制台,外部旧链接与搜索索引也该跟着换过去。
 * 307 会让每次旧链接都多一次服务端往返,还留着「以后可能搬回来」的模糊语义。
 *
 * **为什么还要透传 `?oauth=`**:云端的第三方回调仍然把结果送到
 * `/<locale>/account?oauth=created|existing`(`cloud/api/oauth.py`,这笔改动不碰 cloud)。
 * 308 不会自动带上原查询串,所以这里显式拼回去,让「已创建 / 已绑定到已有账号」那句提示
 * 继续在控制台出现;其他查询参数没有意义,一律丢掉。
 *
 * **路由分组保持 `(auth)`**:地址 `/account` 与目录归属是两件事 —— `route-groups.test.mjs`
 * 钉着「账号路由在 (auth) 组」,分组本身不该因为这一页不再画账号壳就被拆掉。
 * 账号壳仍由登录 / 注册页使用,不在这里渲染。
 */
export default async function AccountPage({
  params,
  searchParams,
}: {
  params: Params;
  searchParams: SearchParams;
}) {
  const { locale } = await params;
  if (!isLocale(locale)) notFound();

  const { oauth } = await searchParams;
  const outcome = parseOAuthOutcome(oauth);
  permanentRedirect(`/${locale}/dashboard${outcome ? `?oauth=${outcome}` : ""}`);
}
