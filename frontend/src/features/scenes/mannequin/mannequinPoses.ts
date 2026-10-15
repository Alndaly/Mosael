import type { MannequinPose } from "./mannequinRig";

/**
 * 姿势预设:关节角度表 + 髋部下移。本期「动作」就到这一层 —— 不做关键帧动画,
 * 预设就是能复现的"动作截图"。表是数据,姿势对不对由 `mannequinPoses.test.ts` 钉
 * (关节名合法、角度有限且在 ±180°),人偶层级保证了「转髋全身跟、转肩手臂跟」。
 *
 * 角度约定(见 mannequinRig):四肢段沿 -Y 下垂、面朝 +Z;X 负角往前摆,
 * 左臂(+X 侧)Z 正角向外抬。坐/蹲带 `hipsDrop`(米):纯旋转放不下去身体。
 */
export const MANNEQUIN_POSES: Record<string, MannequinPose> = {
  /** 站:基本直立,手臂微微外张 —— 木头人偶的"出厂姿态"。 */
  stand: {
    angles: {
      upperArmL: [0, 0, 8],
      upperArmR: [0, 0, -8],
    },
  },
  /** 走:左右腿前后分、膝盖随屈,对侧手臂反摆,躯干带一点反向拧转。 */
  walk: {
    angles: {
      hips: [0, 6, 0],
      spine: [0, -4, 0],
      thighL: [-25, 0, 0],
      thighR: [18, 0, 0],
      shinL: [18, 0, 0],
      shinR: [8, 0, 0],
      footL: [8, 0, 0],
      footR: [-6, 0, 0],
      upperArmL: [18, 0, 6],
      upperArmR: [-20, 0, -6],
      forearmL: [12, 0, 0],
      forearmR: [10, 0, 0],
    },
  },
  /** 坐:大腿放平(绕髋前摆 ~88°)、小腿自然下垂,髋落到椅子高(~0.5 米)。 */
  sit: {
    hipsDrop: 0.44,
    angles: {
      hips: [-4, 0, 0],
      thighL: [-88, 0, -4],
      thighR: [-88, 0, 4],
      shinL: [86, 0, 0],
      shinR: [86, 0, 0],
      footL: [-2, 0, 0],
      footR: [-2, 0, 0],
      spine: [2, 0, 0],
    },
  },
  /** 蹲:腿深屈、膝过脚尖补偿,躯干前倾,髋沉到 ~0.45 米,手臂前伸保持平衡。 */
  squat: {
    hipsDrop: 0.5,
    angles: {
      hips: [12, 0, 0],
      spine: [8, 0, 0],
      chest: [8, 0, 0],
      head: [-14, 0, 0],
      thighL: [-72, 0, -6],
      thighR: [-72, 0, 6],
      shinL: [102, 0, 0],
      shinR: [102, 0, 0],
      footL: [24, 0, 0],
      footR: [24, 0, 0],
      upperArmL: [-48, 0, 10],
      upperArmR: [-48, 0, -10],
      forearmL: [24, 0, 0],
      forearmR: [24, 0, 0],
    },
  },
  /** 举手:双臂上举过头,肘部微屈,头略仰 —— 「投降」式全身伸展参考。 */
  armsUp: {
    angles: {
      head: [-8, 0, 0],
      upperArmL: [0, 0, 152],
      upperArmR: [0, 0, -152],
      forearmL: [0, 0, 14],
      forearmR: [0, 0, -14],
      spine: [-4, 0, 0],
    },
  },
};

/** 预设的姿势名(数据键),顺序即界面顺序。 */
export const MANNEQUIN_POSE_ORDER = ["stand", "walk", "sit", "squat", "armsUp"] as const;

/** 一个姿势表合不合法:键都得是认得的关节,角度得是有限数且在 ±180° 里。 */
export function poseIsValid(pose: MannequinPose, joints: readonly string[]): boolean {
  return Object.entries(pose.angles).every(
    ([name, angles]) =>
      joints.includes(name) &&
      angles.length === 3 &&
      angles.every((a) => Number.isFinite(a) && Math.abs(a) <= 180),
  );
}
