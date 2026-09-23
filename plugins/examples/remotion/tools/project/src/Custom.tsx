/**
 * 占位。**每次自定义渲染都会被换成智能体写的那份**(在一份独立的工程拷贝里,不动这一份)。
 * 它存在只是为了让共享工程能打包:Root 里引用了它。
 */
import React from "react";
import { AbsoluteFill } from "remotion";

export default function Custom(): React.ReactElement {
  return <AbsoluteFill style={{ background: "#000" }} />;
}
