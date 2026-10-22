/** 内嵌浏览器的身份(见 view-identity.cjs):按平台决定给干净 Chrome UA 还是如实声明 Electron。 */
export declare const CHROME_IDENTITY_EXEMPT: Set<string>;
export declare function cleanChromeUserAgent(userAgent: string): string;
export declare function identityForPlatform(platform: string | null | undefined): "chrome" | "electron";

/** 一枚自洽的 Chrome 身份(交给 CDP 的 Emulation.setUserAgentOverride)。 */
export interface ChromeIdentityOverride {
  userAgent: string;
  acceptLanguage: string;
  platform: string;
  userAgentMetadata: {
    brands: Array<{ brand: string; version: string }>;
    fullVersionList: Array<{ brand: string; version: string }>;
    fullVersion: string;
    platform: string;
    platformVersion: string;
    architecture: string;
    model: string;
    mobile: boolean;
    bitness: string;
  };
}
export declare function chromeIdentityOverride(
  userAgent: string,
  options?: { platform?: NodeJS.Platform; arch?: string; systemVersion?: string },
): ChromeIdentityOverride | null;
