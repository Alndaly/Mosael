/** 内嵌浏览器的身份(见 view-identity.cjs):按平台决定给干净 Chrome UA 还是如实声明 Electron。 */
export declare const CHROME_IDENTITY_EXEMPT: Set<string>;
export declare function cleanChromeUserAgent(userAgent: string): string;
export declare function identityForPlatform(platform: string | null | undefined): "chrome" | "electron";
