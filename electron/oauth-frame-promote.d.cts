/** 子框架里的登录回调提到顶层(见 oauth-frame-promote.cjs)。 */
export declare function registrableDomain(hostname: string): string;
export declare function shouldPromoteFrameNavigation(frameUrl: string, topUrl: string): boolean;
