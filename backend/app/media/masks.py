"""蒙版:从一份源图的像素算出灰度蒙版,做形状运算,落盘(ADR 0056 决定 6)。

## 蒙版是什么,照抄契约,别顺手改

**灰度图、白 = 要改的地方** —— 和要改的那张图一起给(见
`app/ai/providers/contracts/generation.py` 的 `MASK`:白色是要改的地方)。它**不是一张带 alpha 的图**:
ComfyUI 插件那条注入的路读的是**红通道**(`plugins/bundled/comfyui/tools/graph.py` 的 `_MASK_CHANNEL`,
注释里写着带透明通道的图读出来是整块不透明),一张带 alpha 的图传过去会**静默地什么都不重绘**。
所以这里每交出一张蒙版都守着两条:

- `r = g = b`(灰度;灰度图里红通道就是那个灰);
- alpha 一律不透明。

守法的办法是**根本不写出 alpha 通道**:落盘走 PIL 的 `L` 模式(见 `write_mask_png`),蒙版在内存里
也是单通道的 `bytes`(一像素一个字节),四通道那种排法只在**读源图**时出现一次(见 `read_rgba`)。

## 和前端画布那一份的关系

画笔、橡皮、矩形/椭圆画出来的那份走的是同一套规则(阈值按 Rec.601 加权、`>=` 判白、羽化三遍盒式
模糊、四边夹取),读它看 `frontend/src/lib/maskPixels.ts`。这里的阈值和羽化是照着它写的,不是另立
一套:同一个阈值、同一张底图,两边该切出同一串字节。这条"同一串字节"由 `contracts/mask-cases.json`
钉着(两侧读**同一份**语料、逐字节比),改这里之前先看那边,反过来也一样。

## 尺寸约定

`size` 一律是 `(width, height)`(和 PIL 的 `Image.size` 一样);一份 RGBA 像素是四通道、长度 =
`width * height * 4`(和 canvas 的 `ImageData.data` 一样)。蒙版本身是单通道、长度 = `width * height`。
"""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np
from PIL import Image, ImageOps

from app.core.i18n import LocalizedError

#: 从源图的哪一样算阈值。请求体里那个 `source` 字段的合法取值。
LUMINANCE = "luminance"
ALPHA = "alpha"
SOURCES = (LUMINANCE, ALPHA)

#: 一像素几个通道(RGBA,和 canvas 的 ImageData 一样)。
CHANNELS = 4
#: Rec.601 —— 和 `lib/maskPixels.ts` 的 LUMA_* 同一组系数:底图不是灰的,按亮度加权才和眼睛看到的「亮」一致。
LUMA_R, LUMA_G, LUMA_B = 0.299, 0.587, 0.114
#: 羽化三遍盒式模糊(≈ 高斯,中心极限),和前端一遍一遍跑的次数一样。
FEATHER_PASSES = 3

MASK_FILENAME = "mask.png"


class MaskError(LocalizedError, ValueError):
    """这份像素算不出蒙版。带文案 key(`maskErr_*`),api 那一层翻成状态码。"""


def clamp01(value: float) -> float:
    """0..1 之外的一律夹回来;不是数的(NaN、inf)当 0。

    和 `lib/maskPixels.ts` 的 `clamp01` 一样 —— 界面上那根滑块的原始值就是按它解释的。
    """
    return 0.0 if not math.isfinite(value) else min(1.0, max(0.0, value))


def _cut(threshold: float) -> float:
    """阈值(0..1)换算成 0..255 的那条线。0 全白、1 只剩纯白,两头都是合法输入,不特殊处理。"""
    return clamp01(threshold) * 255


def _flat(mask) -> bytes:
    """一份单通道蒙版摊成字节。`bytes` / `bytearray` / numpy 数组都收。"""
    if isinstance(mask, bytes):
        return mask
    if isinstance(mask, bytearray):
        return bytes(mask)
    return np.ascontiguousarray(mask, dtype=np.uint8).tobytes()


def _size_of(size: tuple[int, int]) -> tuple[int, int]:
    width, height = int(size[0]), int(size[1])
    if width < 1 or height < 1:
        raise MaskError("maskErr_badSize", width=width, height=height)
    return width, height


def _shape(pixels, size: tuple[int, int]) -> np.ndarray:
    """一份 RGBA 像素摊成 `(height, width, 4)` 的 uint8。长度对不上直接报错 ——

    按错的宽度重排像素,出来的是一张谁也认不出的图,而蒙版这东西的失效方式是**静默**的
    (读出来全空 = 什么都不重绘),宁可当场炸。
    """
    width, height = _size_of(size)
    raw = np.frombuffer(bytes(pixels), dtype=np.uint8)
    expected = width * height * CHANNELS
    if raw.size != expected:
        raise MaskError("maskErr_badPixels", expected=expected, got=int(raw.size))
    return raw.reshape(height, width, CHANNELS)


def _array(mask, size: tuple[int, int]) -> np.ndarray:
    """一份单通道蒙版摊成 `(height, width)` 的 uint8。长度对不上直接报错,理由同 `_shape`。"""
    width, height = _size_of(size)
    raw = np.frombuffer(_flat(mask), dtype=np.uint8)
    if raw.size != width * height:
        raise MaskError("maskErr_badPixels", expected=width * height, got=int(raw.size))
    return raw.reshape(height, width)


def _channels(pixels, size: tuple[int, int]) -> tuple[np.ndarray, np.ndarray]:
    """`(灰度, alpha)` 两份 `(height, width)` 的数组。

    灰度按 Rec.601 在 **float64** 里算:JS 的数是双精度,用 float32 会在阈值那一线上切出和前端
    不一样的图(差一个像素的边,而那正好是羽化过的那条边),这里也没有哪一处需要省那点内存。

    逐通道取而不是把整份 RGBA 先转成 float64:后者对一张 4K 图要多占四倍内存(四个通道里只用到
    三个,而且转的是 uint8 的那个副本)。
    """
    shaped = _shape(pixels, size)
    red, green, blue, alpha = (shaped[:, :, index] for index in range(CHANNELS))
    return LUMA_R * red + LUMA_G * green + LUMA_B * blue, alpha


def _as_mask(white: np.ndarray) -> bytes:
    """二值结果写回单通道蒙版:非黑即白(255 / 0)。"""
    return np.where(white, 255, 0).astype(np.uint8).tobytes()


def mask_from_luminance(pixels, size: tuple[int, int], threshold: float = 0.5) -> bytes:
    """**按亮度**阈值二值化:亮度 ≥ `threshold` 的变白(要改的地方),其余变黑。

    `threshold` 是 0..1。0 全白、1 只剩纯白 —— 两头都是合法输入,不特殊处理。源图直接喂进来也行
    (灰阶加权对灰像素就是它自己)。
    """
    gray, _ = _channels(pixels, size)
    return _as_mask(gray >= _cut(threshold))


def mask_from_alpha(pixels, size: tuple[int, int], threshold: float = 0.5) -> bytes:
    """**按 alpha** 阈值二值化:不透明的地方变白。

    抠好的 PNG(主体实、背景透)走这一条就是「把它抠出来」。源图没有透明通道时是整块白 ——
    那不是这里算错,是那张图本来就没有透的地方。
    """
    _, alpha = _channels(pixels, size)
    return _as_mask(alpha >= _cut(threshold))


def invert_mask(mask) -> bytes:
    """反选:黑变白、白变黑。

    灰的(羽化过的边)按 `255 - v` 翻,边翻过来还是同样软的一条边 —— 不是重新二值化。
    """
    return (255 - np.frombuffer(_flat(mask), dtype=np.uint8)).astype(np.uint8).tobytes()


def _extremum_along(mask: np.ndarray, reach: int, axis: int, *, maximum: bool) -> np.ndarray:
    """沿一个轴取 `[i-reach, i+reach]` 这一段的极大(扩张)/ 极小(收缩)值 —— 一维形态学。

    **边界按夹取**:取样点越界就取边上那个像素(`np.pad(..., mode="edge")` 就是这个意思)。
    补零的话贴着边的那一圈会自己缩掉一块,而蒙版的边常常正是要改的地方 —— 前端羽化那一段
    写的是同一条理由。

    窗口一格一格并进结果里(`out=`,就地累加),不把 2r+1 个窗口堆成一个大数组再 reduce ——
    半径 256 时那个堆法要按 513 份图像分配内存,而这里只要两份。
    """
    if reach < 1:
        return mask
    pad = ((0, 0), (reach, reach)) if axis == 1 else ((reach, reach), (0, 0))
    padded = np.pad(mask, pad, mode="edge")
    length = mask.shape[axis]
    result = np.take(padded, range(reach, reach + length), axis=axis).copy()
    keep = np.maximum if maximum else np.minimum
    for offset in range(1, reach + 1):
        for start in (reach - offset, reach + offset):
            keep(result, np.take(padded, range(start, start + length), axis=axis), out=result)
    return result


def grow_mask(mask, size: tuple[int, int], radius: int) -> bytes:
    """扩张(`radius` > 0)/ 收缩(`radius` < 0)`|radius|` 个像素,**形态学**。

    扩张取窗口最大值,收缩取窗口最小值,窗口是 `(2r+1)×(2r+1)` 的正方形。两轴**分开跑** ——
    正方形结构元是可分离的(两轴各自夹取,合起来就是二维那个窗口),结果和不分开一样,代价从
    r² 遍降到 2r 遍。灰的(羽化过的边)照灰的取最大 / 最小,不先二值化:那一圈软边是用户自己
    调出来的,不该被这一步啃掉。

    半径按图像的长边封顶:扩张半个图宽和扩张整个图宽是同一个结果(全白 / 全黑),再往上只是
    白算一遍。`radius == 0` 原样返回。
    """
    if radius == 0:
        return _flat(mask)
    source = _array(mask, size)
    maximum = radius > 0
    reach = min(abs(int(radius)), max(source.shape))
    grown = _extremum_along(source, reach, 1, maximum=maximum)
    grown = _extremum_along(grown, reach, 0, maximum=maximum)
    return grown.astype(np.uint8).tobytes()


def _box_blur_axis(channel: np.ndarray, reach: int, axis: int) -> np.ndarray:
    """一趟盒式模糊:窗口是 `[i-reach, i+reach]`,边上的取样点夹取(见 `_extremum_along`)。

    用前缀和跑。前端是一格一格加减的滑动窗口 —— 那些和都是整数、双精度里精确,和这里的差值
    逐位相等,但这里不必在 Python 里逐行循环。**每跑完一趟落回 float32**:前端那一趟写进的是
    `Float32Array`,精度得跟着它,不然三趟下来会差出肉眼看不见、但两边对不上的半格。
    """
    if reach < 1:
        return channel
    pad = ((reach, reach), (0, 0)) if axis == 0 else ((0, 0), (reach, reach))
    padded = np.pad(channel.astype(np.float64), pad, mode="edge")
    #: 前缀和就地算(`padded` 本来就是这一趟自己的副本),省一份整图大小的临时数组。
    totals = np.cumsum(padded, axis=axis, out=padded)
    #: 前面接一格 0:`totals[j]` 从此是 `padded[0..j-1]` 的和,窗口两端可以直接相减。
    totals = np.concatenate([np.zeros_like(np.take(totals, [0], axis=axis)), totals], axis=axis)
    length = channel.shape[axis]
    span = 2 * reach + 1
    upper = np.take(totals, np.arange(span, span + length), axis=axis)
    lower = np.take(totals, np.arange(0, length), axis=axis)
    return ((upper - lower) / span).astype(np.float32)


def _half_up(value: float) -> int:
    """四舍五入,**半数进位**(`floor(x + 0.5)`),不是 Python 内建 `round` 的「半数取偶」。

    `round(0.5) == 0`、`round(2.5) == 2`,而前端那句 `Math.round` 是半数进位(`0.5 → 1`、`2.5 → 3`):
    差这一格,`feather = 2.5` 在后端是 2 个像素、在编辑器里是 3 个 —— 同一组参数、两张图,而两边都
    看不出错(见 `contracts/mask-cases.json` 里那几条 `.5`)。同一个规则在 `feather_mask` 里用了两次:
    半径(这里)和往回写(那里末尾那一句 `floor(x + 0.5)`)。
    """
    return math.floor(value + 0.5)


def feather_mask(mask, size: tuple[int, int], radius: float) -> bytes:
    """羽化:把边晕开 `radius` 个像素。

    三遍盒式模糊 ≈ 高斯(中心极限),够用而且没有系数要调。单通道跑 —— 羽化只对灰度有定义,
    四通道各跑一遍是四倍工作量、结果还一样。边缘夹取,理由同 `grow_mask`。`radius < 1` 什么都不做
    (0.4px 的模糊看不出来,却是六遍全画布扫描)。

    `radius` 是浮点,**决定结果的是取整后的那一格** `reach = floor(radius + 0.5)` —— 和往回写
    (`floor(x + 0.5)`)同一条规则,都对齐前端的 `Math.round`,不是 numpy / Python 缺省的「半数取偶」。
    半格的差看着无所谓,但同一张蒙版在两边该是同一串字节:所以 `feather = 0.5` 两边都是 1 格
    (不是"后端不羽化、编辑器羽化"),`feather = 2.5` 两边都是 3 格。
    """
    reach = _half_up(radius)
    if reach < 1:
        return _flat(mask)
    channel = _array(mask, size).astype(np.float32)
    #: 一横一纵 = 一遍;三遍下来,权重分布已经贴着高斯了。
    for _ in range(FEATHER_PASSES):
        channel = _box_blur_axis(_box_blur_axis(channel, reach, 1), reach, 0)
    return np.floor(channel + np.float32(0.5)).clip(0, 255).astype(np.uint8).tobytes()


def write_mask_png(target: Path, mask, size: tuple[int, int]) -> Path:
    """把一份单通道蒙版写成 PNG(模式 `L`)。

    **`L` 模式的 PNG 里根本没有 alpha 通道** —— 契约那条「灰、不透明」就落在这里,不靠调用方记得。
    走 `RGBA` 存的话会多出一个全 255 的通道:读回来 `r=g=b` 是成立的,但那一层要靠在别处再擦一遍,
    而漏擦的失效方式是静默的。
    """
    width, height = _size_of(size)
    data = _flat(mask)
    if len(data) != width * height:
        raise MaskError("maskErr_badPixels", expected=width * height, got=len(data))
    target.parent.mkdir(parents=True, exist_ok=True)
    Image.frombytes("L", (width, height), data).save(target, "PNG")
    return target


def read_rgba(source: Path) -> tuple[bytes, tuple[int, int]]:
    """源图的 RGBA 像素和尺寸(`(width, height)`)。

    手机拍的图先按 EXIF 摆正 —— 不摆正的话「按亮度取上半张」取到的是侧着的那半张,而用户在界面上
    看的是正的那张(和 domain/assets/image_grid 切宫格前的处理是同一件事)。
    """
    with Image.open(source) as opened:
        image = ImageOps.exif_transpose(opened).convert("RGBA")
        return image.tobytes(), image.size


def generate_mask(
    source: Path,
    target: Path,
    *,
    source_kind: str = LUMINANCE,
    threshold: float = 0.5,
    invert: bool = False,
    grow: int = 0,
    feather: float = 0,
) -> Path:
    """源图 → 一张灰度蒙版 PNG,落在 `target`。**只碰这两个路径**,素材库那一层的事不在这里。

    四步的先后是定死的:**阈值 → 反选 → 扩张/收缩 → 羽化**。

    - 阈值一定在最前:后面三步都是对已经分好黑白的那张图做的,先羽化再阈值等于把羽化扔掉;
    - 反选在扩张之前:反选和扩张换不了序(先扩后翻 = 先翻后缩),这里说的是「翻过来,再按这个半径
      长 / 缩」—— 用户点的是反选那一下,后面的形状是对反选后的结果说的;
    - 羽化一定在最后:它是唯一一个把边弄软的步骤,放前面会被后面的形态学再啃硬。
    """
    if source_kind not in SOURCES:
        raise MaskError("maskErr_unknownSource", source=source_kind)
    pixels, size = read_rgba(source)
    if source_kind == ALPHA:
        mask = mask_from_alpha(pixels, size, threshold)
    else:
        mask = mask_from_luminance(pixels, size, threshold)
    if invert:
        mask = invert_mask(mask)
    if grow:
        mask = grow_mask(mask, size, grow)
    if feather:
        mask = feather_mask(mask, size, feather)
    return write_mask_png(target, mask, size)


__all__ = [
    "ALPHA",
    "CHANNELS",
    "FEATHER_PASSES",
    "LUMINANCE",
    "MASK_FILENAME",
    "SOURCES",
    "MaskError",
    "clamp01",
    "feather_mask",
    "generate_mask",
    "grow_mask",
    "invert_mask",
    "mask_from_alpha",
    "mask_from_luminance",
    "read_rgba",
    "write_mask_png",
]
