/** 登录协议转发(见 external-login-schemes.cjs)。只做一件事:把 `weixin://` 这类交给系统。 */
export declare const LOGIN_SCHEMES: Set<string>;
export declare function isExternalLoginUrl(url: string): boolean;
export declare function forwardExternalLogin(
  contents: Electron.WebContents,
  openExternal: (url: string) => Promise<void> | void,
): unknown;
