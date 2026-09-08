"""Workspace-owned scene revisions and bounded, self-contained glTF imports.

**为什么抛领域异常而不是 HTTPException**:场景不只从路由进来 —— 画板保存要校验它引用的
3D 场景、MCP 的 `get_scene` / `edit_scene` 也走这里。领域层抛 FastAPI 的异常,这些非 HTTP 的
调用方就得反过来 catch 再翻回自己的领域错误。状态码由边界统一翻(见 main.py 的处理器),
与 `domain/permissions`、`domain/notes` 同构。
"""
import json
import struct
from sqlalchemy import select, update
from sqlalchemy.orm import Session
from app.db.models import Scene3D, Scene3DRevision, Scene3DModel
from app.db.model_base import now
from app.domain.scene_types import SceneContent


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


#: 导入模型的体积上限。**只此一处** —— 路由读文件、Blender 互通读回传文件都引它;
#: 此前 25 MB 这个数字在五个地方各写了一遍,改一处而漏改另一处不会有任何提示,
#: 只会变成"路由收下了、领域又拒了"这种前后不一。
#:
#: 100 MB 是给**真实工程**留的余量:手工准备一个模型时 25 MB 够用,而「取回 Blender 当前
#: 场景」进来的是别人做好的工程,贴图一嵌进 GLB 就轻松越过 25 MB。真正约束"能不能实时编辑"
#: 的是下面的节点/网格上限(5000 / 2000),字节数大头是贴图,那部分 three.js 扛得住。
MODEL_LIMIT_BYTES = 100 * 1024 * 1024
#: 读文件时多读一个字节,好分辨"正好到上限"和"超了"。
MODEL_READ_LIMIT = MODEL_LIMIT_BYTES + 1


def validate_model(data: bytes) -> str:
    if len(data) > MODEL_LIMIT_BYTES:
        raise SceneTooLarge(
            f"模型 {len(data)/1024/1024:.1f} MB，超出上限 {MODEL_LIMIT_BYTES//1024//1024} MB。"
            "常见的减法:在 Blender 里隐藏或删掉用不到的物体、把贴图降到 2K、"
            "或者把场景拆成几个分别导入。")
    fmt = "glb" if data[:4] == b"glTF" else "gltf"
    try:
        if fmt == "glb":
            magic, version, length, chunk_size, chunk_type = struct.unpack("<4sIIII", data[:20])
            if version != 2 or length != len(data) or chunk_type != 0x4E4F534A or chunk_size > len(data)-20:
                raise ValueError("这不是一个有效的 GLB 文件（文件头读不通）。")
            doc = json.loads(data[20:20+chunk_size])
        else:
            doc = json.loads(data)
        if doc.get("asset", {}).get("version") != "2.0":
            raise ValueError("需要 glTF 2.0 格式的模型。")
        # Never allow imported models to fetch network URLs or local files.
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
            raise ValueError(f"模型有 {len(doc.get('nodes', []))} 个节点、{len(doc.get('meshes', []))} 个网格，超出实时编辑的上限（5000 / 2000）。请在 Blender 里合并物体或减少细分后重试。")
    except (ValueError, TypeError, AttributeError, struct.error, RecursionError) as exc:
        raise SceneDomainError(str(exc)) from exc
    return fmt


def import_model(db: Session, scene_id: str, name: str, data: bytes) -> Scene3DModel:
    fmt = validate_model(data)
    model = Scene3DModel(scene_id=scene_id, name=name[:160], format=fmt, data=data)
    db.add(model)
    db.commit()
    db.refresh(model)
    return model


def create_scene_with_model(db: Session, *, workspace_id: str, name: str, content: SceneContent,
                            model_id: str, model_name: str, model_format: str,
                            model_data: bytes) -> Scene3D:
    """建一个场景,连同它自带的那份导入模型和初始修订,**一个事务里落地**。

    Blender 接回来的场景就是这个形状:场景、模型、修订三样要么一起在,要么一起不在 ——
    少了模型的场景在编辑器里是个空壳,而没有场景的模型没有任何入口能删掉。

    `create_scene` 明确拒绝内容里带 `model_id`(先建场景、再导模型),这里是那条规则的
    **唯一例外**:模型的字节此刻就在手上,分两步反而必然留下一个中间态。

    它存在的另一个理由是**数据归属**(ADR-0003):Scene3D / Scene3DModel / Scene3DRevision
    三张表归这个模块,所以行只在这里建;Blender 互通调它,而不是自己 `Scene3D(...)`。
    """
    scene = Scene3D(workspace_id=workspace_id, name=name[:160], content=content.model_dump(mode="json"))
    db.add(scene)
    db.flush()
    db.add(Scene3DModel(id=model_id, scene_id=scene.id, name=model_name[:160],
                        format=model_format, data=model_data))
    db.add(Scene3DRevision(scene_id=scene.id, revision=1,
                           snapshot={"name": scene.name, "content": scene.content}))
    db.commit()
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
