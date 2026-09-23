/**
 * 两个画面:套模板的「讲解视频」,和智能体自己写的「自定义动画」。
 *
 * 尺寸、帧率、总长都从输入里来(calculateMetadata)—— 这里写的只是占位,Remotion 要求有。
 */
import React from "react";
import { Composition } from "remotion";

import Custom from "./Custom";
import { Explainer, type ExplainerProps, timeline } from "./Explainer";

export type CustomProps = { width: number; height: number; fps: number; seconds: number; data?: unknown };

export const Root: React.FC = () => (
  <>
    <Composition
      id="Explainer"
      component={Explainer}
      durationInFrames={1}
      fps={30}
      width={1920}
      height={1080}
      defaultProps={{ title: "", sections: [], width: 1920, height: 1080, fps: 30 } as ExplainerProps}
      calculateMetadata={({ props }) => ({
        durationInFrames: Math.max(1, timeline(props).total),
        fps: props.fps, width: props.width, height: props.height,
      })}
    />
    <Composition
      id="Custom"
      component={Custom as React.FC<CustomProps>}
      durationInFrames={1}
      fps={30}
      width={1920}
      height={1080}
      defaultProps={{ width: 1920, height: 1080, fps: 30, seconds: 1 } as CustomProps}
      calculateMetadata={({ props }) => ({
        durationInFrames: Math.max(1, Math.round(props.seconds * props.fps)),
        fps: props.fps, width: props.width, height: props.height,
      })}
    />
  </>
);
