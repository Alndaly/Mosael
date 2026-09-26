"""让插件自己走一次 OAuth,而不是让用户手抄 refresh_token。

现状是这样的:百度网盘那个插件要用户去开放平台注册应用拿 AppKey/SecretKey(这一步替代不了),
然后**自己拼一个授权链接、在浏览器里走一遍、把 code 换成 token、再把 refresh_token 抄回来**。
中间那一段全是机械动作,而每一步都能抄错 —— 参数名错一个字,换回来的是一句英文报错。

所以这里做的就是那一段:拼链接、拿 code 换令牌、把令牌写回插件声明的那几个凭据键。

**为什么不用 mosael:// 接回调。** 自定义协议是外部输入面 —— 任何网页只要
`location = "mosael://…"` 就能触发它,所以 electron/system/deepLink 明确只认导航、别的一律不接。
拿它收令牌等于让任何网站都能塞一个进来。默认走 `oob`(对方把 code 显示出来,人贴回来):
多一次粘贴,换来的是这条通路上没有任何可伪造的输入。

**为什么不在本机开监听端口。** 那是原生应用 OAuth 的标准做法(RFC 8252),但重定向地址要
在对方的控制台里预先登记,而后端端口是会变的(打包版会挑一个空闲端口)。登记一个固定端口
就等于要求那个端口永远可用,而它并不。
"""

from __future__ import annotations

from typing import Any
from urllib.parse import urlencode

from app.core.i18n import LocalizedError
from app.domain.plugins.manifest import Field, Manifest, OAuthSpec

#: 一个声明了 oauth 的连接**授权到哪一步了**(插件页连接卡片上那一条状态)。
#: 没声明 oauth 的连接不谈授权,是空串。
UNAUTHORIZED = "unauthorized"
AUTHORIZED = "authorized"
#: 令牌填着,但插件上一次调用时说「对方不再接受它」(响应里的 `reauthorize: true`)。
REJECTED = "rejected"


class PluginOAuthError(LocalizedError, RuntimeError):
    """面向用户的错误。消息要说清楚下一步做什么。带文案 key(`pluginErr_oauth*`)。"""


def spec_of(manifest: Manifest) -> OAuthSpec:
    if manifest.oauth is None:
        raise PluginOAuthError("pluginErr_oauthNotDeclared")
    return manifest.oauth


def fills(spec: OAuthSpec, credentials: list[Field]) -> list[Field]:
    """授权流程会写的那几格凭据(`stores` 指向的),按清单里的先后。

    界面据此把它们收进「手动填写」:它们本来就由「去授权」填,不该和 AppKey 一样摆成主输入。
    """
    targets = set(spec.stores.values())
    return [one for one in credentials if one.key in targets]


def authorization_state(spec: OAuthSpec, credentials: list[Field], filled: set[str], *, rejected: bool) -> str:
    """这个连接授权到哪一步。**纯函数**,只看「哪几格填着」这个布尔,不碰令牌本身。

    · 授权会写的格子里,**必填的都填了**才算授权过(百度:Refresh Token 必填、Access Token 可以空着
      让插件自己换);一格都没标必填的,填了任意一格就算;
    · 填着、但插件上一次说对方不认了(`rejected`),就是「需要重新授权」—— 格子非空不等于令牌还有效,
      而这一点只有真去调过一次的插件知道。
    """
    targets = fills(spec, credentials)
    required = [one.key for one in targets if one.required]
    done = all(key in filled for key in required) if required else any(one.key in filled for one in targets)
    if not done:
        return UNAUTHORIZED
    return REJECTED if rejected else AUTHORIZED


def authorize_url(spec: OAuthSpec, credentials: dict[str, str]) -> str:
    """拼授权链接。**纯函数** —— 参数名抄错是这条路上最常见的错,而它值得被测。"""
    client_id = (credentials.get(spec.client_id_field) or "").strip()
    if not client_id:
        # 先填 AppKey 再授权。反过来的话,用户会点进一个 invalid_client 的页面,
        # 而那句报错不会告诉他缺的是这一格。
        raise PluginOAuthError("pluginErr_oauthNeedsClientId", field=spec.client_id_field)
    query = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": spec.redirect_uri,
    }
    if spec.scope:
        query["scope"] = spec.scope
    joiner = "&" if "?" in spec.authorize_url else "?"
    return f"{spec.authorize_url}{joiner}{urlencode(query)}"


def token_request(spec: OAuthSpec, credentials: dict[str, str], code: str) -> dict[str, str]:
    """换令牌要发出去的参数。**纯函数**,同上。"""
    code = code.strip()
    if not code:
        raise PluginOAuthError("pluginErr_oauthNoCode")
    payload = {
        "grant_type": "authorization_code",
        "code": code,
        "client_id": (credentials.get(spec.client_id_field) or "").strip(),
        "redirect_uri": spec.redirect_uri,
    }
    if spec.client_secret_field:
        payload["client_secret"] = (credentials.get(spec.client_secret_field) or "").strip()
    return payload


def credentials_from_token(spec: OAuthSpec, response: dict[str, Any]) -> dict[str, str]:
    """把令牌响应映射成「要写进哪几个凭据键」。

    **对方没给的字段不写。** 有些提供方在刷新时只回 access_token,把缺失当空串写回去会把
    已有的 refresh_token 抹掉 —— 而那一份丢了就得重新走一遍授权。
    """
    if not isinstance(response, dict):
        raise PluginOAuthError("pluginErr_oauthTokenNotObject")
    # 对方用自己的字段名报错(error / error_description),原样转出去 —— 它比"授权失败"有用。
    if response.get("error"):
        detail = response.get("error_description") or response.get("error")
        raise PluginOAuthError("pluginErr_oauthFailed", detail=detail)
    out: dict[str, str] = {}
    for field_name, credential_key in spec.stores.items():
        value = response.get(field_name)
        if isinstance(value, (str, int)) and str(value).strip():
            out[credential_key] = str(value).strip()
    if not out:
        raise PluginOAuthError("pluginErr_oauthNoFields")
    return out
