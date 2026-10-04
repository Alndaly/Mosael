import React from "react";

/**
 * 顶栏页面工具要知道「现在是哪个工作区」(截图存进哪个素材库、笔记建在哪)。
 *
 * 顶栏挂在应用最外层 —— 内嵌浏览器亮着时它必须在,哪怕这会儿还没进到工作区 —— 而工作区只有 Studio 里才
 * 确定。所以 Studio 挂上时把工作区报到这里,顶栏照它决定要不要摆工具区;没报(登录页、连接中)就只有导航。
 *
 * 单独一个模块、不引任何 UI:context 的身份就是这一次 createContext 的返回值,模块被热更新重跑一次就换了
 * 一个(见 app/contextIdentity.test.ts)。
 */
export const BrowserToolsWorkspace = React.createContext<{
  workspaceId: string | null;
  setWorkspaceId: (id: string | null) => void;
}>({ workspaceId: null, setWorkspaceId: () => undefined });
