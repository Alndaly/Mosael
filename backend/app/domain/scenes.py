"""Workspace-owned scene revisions and bounded, self-contained glTF imports.

**为什么抛领域异常而不是 HTTPException**:场景不只从路由进来 —— 画板保存要校验它引用的
3D 场景、MCP 的 `get_scene` / `edit_scene` 也走这里。领域层抛 FastAPI 的异常,这些非 HTTP 的
调用方就得反过来 catch 再翻回自己的领域错误。状态码由边界统一翻(见 main.py 的处理器),
与 `domain/permissions`、`domain/notes` 同构。
"""
import json
import shutil
import struct
from pathlib import Path
from uuid import uuid4

from sqlalchemy import select, update
from sqlalchemy.orm import Session
from app.db.models import Scene3D, Scene3DRevision, Scene3DModel
from app.db.model_base import now
from app.domain.scene_types import SceneContent
from app.media.paths import resolve_key, scene_model_dir, scene_model_key
from typing import BinaryIO


class SceneDomainError(ValueError):
    """场景领域说不行。`status` 由子类给,边界照着翻(见 main.py)。"""

    status = 422


class SceneNotFound(SceneDomainError):
    """要么不存在,要么不属于这个工作区 —— 两种情况**同一个答案**,分开答等于告诉外人
    这个 id 是存在的。"""

    status = 404


class SceneConflict(SceneDomainError):
    """场景在,但修订号对不上:别人在你读到写之间存过一版。"""

    status = 409


class SceneTooLarge(SceneDomainError):
    """模型超出体积上限。**413 而不是 422** —— 它答的是"这份文件太大",不是"这份文件不对",
    而用户要做的事也不同(换个模型 vs 修模型)。"""

    status = 413


#: 卡片上画得下的物体数。上限存在的理由是**响应体积**:列表一次最多 200 个场景,
#: 每个都带着它的物体,不设限一个大场景就能把列表页拖垮。40 个之后缩略图上也早已看不清谁是谁。
PREVIEW_OBJECT_LIMIT = 40


def scene_preview(content: dict) -> dict:
    """列表卡片要画的那点东西。

    **这里只挑字段,不解释几何** —— "一个 room 俯视占多大"属于造型知识,它在前端
    (SceneViewport 按同一批 parameters 建 mesh);后端再算一遍就是同一份知识的第二个实现,
    而两份实现必然分岔。所以这里只负责把画得着的字段挑出来、把画不着的留下。

    留下的大头是 `track`:一条运镜轨可以有 100 个关键帧,而缩略图只需要相机走过哪儿,
    所以相机只带位置点,别的物体的轨整条不带(静物的缩略图本来就画它的静止姿态)。
    """
    objects: list[dict] = []
    for raw in content.get("objects", []):
        if len(objects) >= PREVIEW_OBJECT_LIMIT:
            break
        if raw.get("hidden"):
            continue
        parameters = raw.get("parameters") or {}
        item = {
            "kind": raw.get("kind"),
            "position": raw.get("position"),
            "rotation": raw.get("rotation"),
            "scale": raw.get("scale"),
            "color": raw.get("color"),
            "parameters": {k: parameters[k] for k in ("width", "depth", "radius") if k in parameters},
        }
        if raw.get("kind") == "camera":
            item["path"] = [frame.get("position") for frame in (raw.get("track") or []) if frame.get("position")]
        objects.append(item)
    return {"objects": objects}


def get_scene(db: Session, workspace_id: str, scene_id: str) -> Scene3D:
    scene = db.scalar(select(Scene3D).where(Scene3D.id == scene_id, Scene3D.workspace_id == workspace_id))
    if scene is None:
        raise SceneNotFound("3D scene not found")
    return scene


def check_models(db: Session, scene_id: str, content: SceneContent):
    ids = {o.model_id for o in content.objects if o.model_id}
    if ids:
        owned = set(db.scalars(select(Scene3DModel.id).where(Scene3DModel.scene_id == scene_id, Scene3DModel.id.in_(ids))))
        if owned != ids:
            raise SceneDomainError("Imported model does not belong to this scene")


def create_scene(db: Session, workspace_id: str, name: str, content: SceneContent) -> Scene3D:
    if any(o.model_id for o in content.objects):
        raise SceneDomainError("Import models after creating the scene")
    scene = Scene3D(workspace_id=workspace_id, name=name, content=content.model_dump(mode="json"))
    db.add(scene)
    db.flush()
    db.add(Scene3DRevision(scene_id=scene.id, revision=1, snapshot={"name": name, "content": scene.content}))
    db.commit()
    db.refresh(scene)
    return scene


def save_scene(db: Session, scene: Scene3D, base_revision: int, name: str, content: SceneContent) -> Scene3D:
    if scene.revision != base_revision:
        raise SceneConflict("Scene changed elsewhere. Keep your draft and reload before saving.")
    check_models(db, scene.id, content)
    data = content.model_dump(mode="json")
    if data == scene.content and name == scene.name:
        return scene
    result = db.execute(update(Scene3D).where(Scene3D.id == scene.id, Scene3D.revision == base_revision).values(
        name=name, content=data, revision=base_revision+1, updated_at=now()), execution_options={"synchronize_session": False})
    if result.rowcount != 1:
        db.rollback()
        raise SceneConflict("Scene changed elsewhere")
    db.add(Scene3DRevision(scene_id=scene.id, revision=base_revision+1, snapshot={"name": name, "content": data}))
    db.commit()
    db.refresh(scene)
    return scene


#: GLB 的体积上限。**只此一处** —— 路由、Blender 互通都引它。
#:
#: 512 MB 这个数是这样来的:字节现在既不进数据库、也不整份进内存(落盘走分块拷贝,校验只读
#: 文件头,下载走 sendfile),后端这边基本不随文件变大而变贵。剩下的天花板在**浏览器**:
#: 一份 GLB 要先成为 ArrayBuffer、再被 GLTFLoader 解析、贴图再进显存,几份拷贝叠起来。
#: 超过 300 MB 左右开始明显卡的是那一头,不是这一头。真要更大就该压(Draco / KTX2 都支持了),
#: 而不是继续抬这个数。
MODEL_LIMIT_BYTES = 512 * 1024 * 1024

#: 内嵌 glTF 的上限**低得多,而且是有道理的**:它是一整份 JSON,资源全是 base64 塞在里面,
#: 校验必须 `json.loads` 整份 —— 那一下就是文件大小的好几倍内存,没有"只读文件头"这条路。
#: GLB 把资源放在二进制块里,我们只解析前面那段 JSON,所以它可以大得多。
#: 换句话说这不是两个产品决定,是两种格式的代价不同。
EMBEDDED_GLTF_LIMIT_BYTES = 100 * 1024 * 1024


def _limit_for(fmt: str) -> int:
    return MODEL_LIMIT_BYTES if fmt == "glb" else EMBEDDED_GLTF_LIMIT_BYTES


def _refuse_too_large(measured: int, fmt: str) -> None:
    limit_bytes = _limit_for(fmt)
    if measured <= limit_bytes:
        return
    limit = limit_bytes // 1024 // 1024
    actual = f"{measured/1024/1024:.1f}"
    # 真实大小只在**它能多说一句**的时候才报:四舍五入之后恰好等于上限时,写出来就成了
    # "100.0 MB 超出上限 100 MB",读起来像 bug。
    excess = f"（这份 {actual} MB）" if actual != f"{limit}.0" else ""
    advice = (
        "把贴图换成 KTX2、几何用 Draco 压一下(Mosael 都能解),"
        if fmt == "glb"
        else "改导出 GLB —— 内嵌 glTF 要整份解析，所以它的上限低得多。GLB 可以到 "
             f"{MODEL_LIMIT_BYTES // 1024 // 1024} MB。也可以"
    )
    raise SceneTooLarge(
        f"模型超出上限 {limit} MB{excess}。{advice}"
        "或者在 Blender 里隐藏用不到的物体、把贴图降到 2K。")


def _validate_document(doc: object) -> None:
    """校验 glTF 文档本身。**只看结构,不看字节** —— 所以 GLB 只要前面那段 JSON 就够。"""
    if not isinstance(doc, dict) or doc.get("asset", {}).get("version") != "2.0":
        raise ValueError("需要 glTF 2.0 格式的模型。")

    # 导入的模型永远不许去取网址或本地文件。
    def inspect(value, depth=0):
        if depth > 48:
            raise ValueError("模型的结构嵌套太深，无法导入。")
        if isinstance(value, dict):
            for key, child in value.items():
                if key == "uri" and (not isinstance(child, str) or not child.startswith("data:")):
                    raise ValueError("请导出自包含的 GLB（或把资源内嵌进 glTF）—— 模型里引用的外部文件和网址不会被读取。")
                inspect(child, depth+1)
        elif isinstance(value, list):
            for child in value:
                inspect(child, depth+1)

    inspect(doc)
    if len(doc.get("nodes", [])) > 5000 or len(doc.get("meshes", [])) > 2000:
        raise ValueError(f"模型有 {len(doc.get('nodes', []))} 个节点、{len(doc.get('meshes', []))} 个网格，"
                         "超出实时编辑的上限（5000 / 2000）。请在 Blender 里合并物体或减少细分后重试。")


def validate_model_file(path: Path) -> str:
    """校验磁盘上的一份模型,返回格式。**不整份读进内存。**

    GLB 的资源都在后面的二进制块里,我们一个字节都不看 —— 只要文件头(20 字节)和它声明的那段
    JSON。一份 500 MB 的模型,这里读进来的通常是几百 KB。

    内嵌 glTF 没有这条路:它是一整份 JSON,资源是 base64 塞在里面的,不解析完就没法校验。
    它的上限因此低得多(见 EMBEDDED_GLTF_LIMIT_BYTES)。
    """
    size = path.stat().st_size
    try:
        with path.open("rb") as stream:
            head = stream.read(20)
            if head[:4] == b"glTF":
                _, version, length, chunk_size, chunk_type = struct.unpack("<4sIIII", head)
                _refuse_too_large(size, "glb")
                if version != 2 or length != size or chunk_type != 0x4E4F534A or chunk_size > size - 20:
                    raise ValueError("这不是一个有效的 GLB 文件（文件头读不通）。")
                doc = json.loads(stream.read(chunk_size))
                fmt = "glb"
            else:
                _refuse_too_large(size, "gltf")
                stream.seek(0)
                doc = json.loads(stream.read())
                fmt = "gltf"
        _validate_document(doc)
    except SceneTooLarge:
        raise
    except (ValueError, TypeError, AttributeError, struct.error, RecursionError, OSError) as exc:
        raise SceneDomainError(str(exc)) from exc
    return fmt


def validate_model(data: bytes, *, size: int | None = None) -> str:
    """内存里那一份的版本。**只给已经握着字节的调用方** —— 新代码走 `validate_model_file`。"""
    fmt = "glb" if data[:4] == b"glTF" else "gltf"
    _refuse_too_large(size if size is not None else len(data), fmt)
    try:
        if fmt == "glb":
            _, version, length, chunk_size, chunk_type = struct.unpack("<4sIIII", data[:20])
            if version != 2 or length != len(data) or chunk_type != 0x4E4F534A or chunk_size > len(data)-20:
                raise ValueError("这不是一个有效的 GLB 文件（文件头读不通）。")
            doc = json.loads(data[20:20+chunk_size])
        else:
            doc = json.loads(data)
        _validate_document(doc)
    except (ValueError, TypeError, AttributeError, struct.error, RecursionError) as exc:
        raise SceneDomainError(str(exc)) from exc
    return fmt


CHUNK = 1024 * 1024


def _model_slot(workspace_id: str, scene_id: str) -> Path:
    directory = scene_model_dir(workspace_id, scene_id)
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def _peek_format(source: BinaryIO) -> str:
    """看头 4 个字节判格式,再把位置放回去。两种格式的上限不同,所以要先知道是哪种。"""
    where = source.tell()
    magic = source.read(4)
    source.seek(where)
    return "glb" if magic == b"glTF" else "gltf"


def import_model(db: Session, scene: Scene3D, name: str, source: BinaryIO,
                 *, declared_size: int | None = None) -> Scene3DModel:
    """把一份模型收进这个场景。**从流分块搬到磁盘,任何时候都不整份进内存。**

    顺序是:先按声明的大小挡一道(一份 2 GB 的文件不必落盘就能拒绝)、分块拷到 `.part`、
    校验(GLB 只读文件头和那段 JSON)、改名、落行。

    `.part` 这个中间名是有用的:校验没过或落行失败时删掉它,目录里不会留下一个**看起来像
    成品**的文件 —— 那种残骸最难认,它和真模型只差在能不能解析。
    """
    fmt = _peek_format(source)
    if declared_size is not None:
        _refuse_too_large(declared_size, fmt)

    model_id = uuid4().hex
    directory = _model_slot(scene.workspace_id, scene.id)
    staged = directory / f"{model_id}.part"
    try:
        size = 0
        with staged.open("wb") as out:
            while chunk := source.read(CHUNK):
                size += len(chunk)
                # 边搬边挡:调用方没给大小(或给错了)时,这里仍然不会写下一份超限的文件。
                _refuse_too_large(size, fmt)
                out.write(chunk)
        fmt = validate_model_file(staged)
        final = directory / f"{model_id}.{fmt}"
        staged.replace(final)
    except BaseException:
        staged.unlink(missing_ok=True)
        raise

    model = Scene3DModel(id=model_id, scene_id=scene.id, name=name[:160], format=fmt,
                         file_key=scene_model_key(scene.workspace_id, scene.id, final.name), size=size)
    db.add(model)
    try:
        db.commit()
    except Exception:
        db.rollback()
        final.unlink(missing_ok=True)   # 行没落成,文件不留
        raise
    db.refresh(model)
    return model


def model_file(model: Scene3DModel) -> Path:
    """这份模型在磁盘上的位置。"""
    return resolve_key(model.file_key)


def delete_scene_model_files(scene: Scene3D) -> None:
    """删场景时连它的模型文件一起删。**行是 CASCADE 走的,文件没人管** —— 和字体、LUT 同一套
    (`delete_font_files`),由删除那条路显式调用。"""
    directory = scene_model_dir(scene.workspace_id, scene.id)
    if directory.is_dir():
        shutil.rmtree(directory, ignore_errors=True)


def create_scene_with_model(db: Session, *, workspace_id: str, name: str, content: SceneContent,
                            model_id: str, model_name: str, model_format: str,
                            model_source: Path) -> Scene3D:
    """建一个场景,连同它自带的那份导入模型和初始修订,**一个事务里落地**。

    Blender 接回来的场景就是这个形状:场景、模型、修订三样要么一起在,要么一起不在 ——
    少了模型的场景在编辑器里是个空壳,而没有场景的模型没有任何入口能删掉。

    `create_scene` 明确拒绝内容里带 `model_id`(先建场景、再导模型),这里是那条规则的
    **唯一例外**:模型此刻就在手上,分两步反而必然留下一个中间态。

    它存在的另一个理由是**数据归属**(ADR-0003):Scene3D / Scene3DModel / Scene3DRevision
    三张表归这个模块,所以行只在这里建;Blender 互通调它,而不是自己 `Scene3D(...)`。

    收的是**路径不是字节**:一份 500 MB 的模型没有理由为了换个地方而先进内存一趟。
    """
    scene = Scene3D(workspace_id=workspace_id, name=name[:160], content=content.model_dump(mode="json"))
    db.add(scene)
    db.flush()
    directory = _model_slot(workspace_id, scene.id)
    final = directory / f"{model_id}.{model_format}"
    shutil.copyfile(model_source, final)
    size = final.stat().st_size
    db.add(Scene3DModel(id=model_id, scene_id=scene.id, name=model_name[:160],
                        format=model_format, file_key=scene_model_key(workspace_id, scene.id, final.name),
                        size=size))
    db.add(Scene3DRevision(scene_id=scene.id, revision=1,
                           snapshot={"name": scene.name, "content": scene.content}))
    try:
        db.commit()
    except Exception:
        db.rollback()
        final.unlink(missing_ok=True)
        raise
    db.refresh(scene)
    return scene


def apply_scene_operations(db: Session, scene: Scene3D, base_revision: int, objects: list[dict], remove_ids: list[str], shots: list[dict] | None, name: str | None) -> Scene3D:
    """Merge object fields atomically; deletion includes descendants. No executable code."""
    from copy import deepcopy
    from pydantic import ValidationError
    content = deepcopy(scene.content)
    removed = set(remove_ids)
    for _ in range(16):
        removed.update(o['id'] for o in content['objects'] if o.get('parent_id') in removed)
    by_id = {o['id']: o for o in content['objects'] if o['id'] not in removed}
    for patch in objects:
        if not isinstance(patch.get('id'), str):
            raise SceneDomainError('Every object operation needs an id')
        obj = {**by_id.get(patch['id'], {}), **patch}
        if 'parameters' in patch and isinstance(patch['parameters'], dict):
            obj['parameters'] = {**by_id.get(patch['id'], {}).get('parameters', {}), **patch['parameters']}
        by_id[patch['id']] = obj
    content['objects'] = list(by_id.values())
    if shots is not None:
        content['shots'] = shots
    try:
        validated = SceneContent.model_validate(content)
    except ValidationError as exc:
        raise SceneDomainError(str(exc)) from exc
    return save_scene(db, scene, base_revision, name if name is not None else scene.name, validated)
