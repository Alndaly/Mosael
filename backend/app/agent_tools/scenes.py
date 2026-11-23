"""3D 场景与 Blender 互通。

从仓库根的 mcp_server.py 按工具族拆出来(架构体检第 8 条)。登记、调用身份、领域用例的调用方式见 ./registry。
"""

from __future__ import annotations

from typing import Any

from app.agent_tools.registry import (
    confirmation_reply,
    default_workspace_id,
    ImageContent,
    open_card,
    REQUESTED_BY,
    TextContent,
    tool,
    use_case,
    with_images,
)
from app.api.schemas.scenes import SceneCreate, SceneOperations, SceneOut, SceneReferenceOut
from app.domain.blender import use_cases as blender_use_cases
from app.domain.scenes import use_cases as scenes_use_cases, use_cases as scenes

@tool(effect="reads")
def list_scenes(workspace_id: str = "") -> list[dict[str, Any]]:
    """List persistent 3D scenes in the workspace, with object and shot counts."""

    return use_case(scenes_use_cases.list_scenes, workspace_id or default_workspace_id())


@tool(effect="reads")
def get_scene(scene_id: str, workspace_id: str = "") -> dict[str, Any]:
    """Read the current editable 3D scene, objects, materials, camera shots and revision.
    Positions/dimensions are metres; rotations are XYZ degrees. Read before editing.
    This returns geometry data, not a rendered image; do not claim visual inspection."""

    return use_case(scenes_use_cases.read, workspace_id or default_workspace_id(), scene_id, out=SceneOut)


@tool(effect="writes")
def create_scene(name: str, workspace_id: str = "") -> dict[str, Any]:
    """Create an empty persistent 3D scene. Then use edit_scene to add geometry and camera shots.
    Uses the user's selected chat model; no specific model or external generation service required."""

    # 同一份请求校验(名字长度、空场景的形状)—— 直接调用例不经过 HTTP,校验不能跟着丢。
    request = SceneCreate(workspace_id=workspace_id or default_workspace_id(), name=name)
    return use_case(scenes_use_cases.create, request.workspace_id, request.name, request.content, out=SceneOut)


@tool(effect="writes", kit="canvas")
def edit_scene(scene_id: str, base_revision: int, objects: list[dict[str, Any]] | None = None,
               remove_ids: list[str] | None = None, shots: list[dict[str, Any]] | None = None,
               name: str | None = None, workspace_id: str = "") -> dict[str, Any]:
    """Edit an actual 3D scene atomically, with undoable immutable revisions. Read get_scene first.
    objects: up to 100 partial updates keyed by id, or new objects with id, name and kind.
    kind: box, sphere, cylinder, plane, room, stairs, table, figure, group, model, light, camera.
    Optional position, rotation and scale are XYZ triples (metres/degrees); parent_id must reference
    a group. parameters: width,height,depth,radius,steps,door_width,door_height. Room has a floor and
    four walls, centered doors in front/back, no ceiling. Stairs climb along +Z. figure is a person
    stand-in (height = parameters.height, shoulders = width). Primitives stand on local y=0; sphere
    center is at radius. color is #RRGGBB; roughness/metalness 0..1. Y is up, floor at y=0.
    Imported models require an existing model_id from this SAME scene; never invent one.
    Cameras are objects: {kind:'camera', position, target:[x,y,z], fov:10..120 (vertical degrees)}.
    A moving camera or object has track:[{time, position, target (cameras), fov (cameras),
    rotation/scale (objects)}]; times strictly increase. remove_ids deletes objects AND descendants.
    shots, when supplied, replaces the shot list: [{id, name, duration:0.1..120,
    aspect:'16:9'|'9:16'|'1:1', easing:'linear'|'smooth', camera_id}] — each shot names the camera
    object that films it; the camera's track is the camera move. Plan collision-free camera paths
    yourself; interpolation does not perform collision avoidance. No executable code is accepted.
    If revision conflicts, re-read and merge; never overwrite changes blindly.
    """

    # 同一份请求校验(对象、删除、镜头的数量上限)。
    request = SceneOperations(
        workspace_id=workspace_id or default_workspace_id(), base_revision=base_revision,
        objects=objects or [], remove_ids=remove_ids or [], shots=shots, name=name,
    )
    return use_case(
        scenes_use_cases.apply_operations, request.workspace_id, scene_id, base_revision=request.base_revision,
        objects=request.objects, remove_ids=request.remove_ids, shots=request.shots, name=request.name, out=SceneOut,
    )


@tool(effect="reads", kit="canvas")
def list_scene_models(workspace_id: str = "") -> list[dict[str, Any]]:
    """Read-only: the imported 3D models available in this workspace, with id, name, format and size.

    Models belong to the WORKSPACE, not to one scene: import (or blender_import_to_scene) once and
    place the same prop in any scene. Use an id here as `model_id` on a `kind: "model"` object in
    edit_scene to place it. view_scene draws these models, so you can check the placement yourself.
    """

    return use_case(scenes_use_cases.list_models, workspace_id or default_workspace_id())


@tool(effect="reads", kit="canvas")
def view_scene(scene_id: str, views: list[str] | None = None, shot_id: str = "", time: float = 0.0,
               workspace_id: str = "") -> list[TextContent | ImageContent]:
    """Read-only: LOOK at a 3D scene — returns rendered images you can see. Free, local, ~1 s per view.

    Call it after edit_scene to check your work instead of trusting the numbers: objects sunk into
    the floor, floating, overlapping, blocking a doorway, or framed badly all show up at a glance.
    views (max 4): 'shot' = what the shot's camera sees at `time` seconds (composition);
    'overview' = the whole scene from a high 3/4 angle; 'top' = plan view (layout, paths);
    'front' / 'side' = elevations (heights, stacking). Default ['shot', 'overview'].
    shot_id picks the shot (default: the first). Graybox only: each object in its own flat color.
    Imported models ARE drawn, using their own base colors. A model that could not be drawn (Draco
    compression, over the triangle budget, missing file) is counted in skipped_models and explained
    in model_warnings — read those instead of assuming the frame is complete.
    """

    data = use_case(
        scenes_use_cases.view, workspace_id or default_workspace_id(), scene_id, views=views or [], shot_id=shot_id, time=time
    )
    return with_images(data)


@tool(effect="reads", kit="canvas")
def blender_inspect(instance_id: str = "", workspace_id: str = "") -> dict[str, Any]:
    """Read-only: what is in the Blender scene the user has open right now — every object's name,
    type, parent, location, rotation (degrees), scale, dimensions (metres) and, for meshes, vertex /
    face counts, modifiers and materials. Blender is Z-up. Call this before blender_execute so your
    code targets objects that exist. Needs the Blender MCP plugin and the Blender add-on running."""

    return use_case(blender_use_cases.inspect, workspace_id or default_workspace_id(), instance_id)


@tool(effect="reads", kit="canvas")
def blender_look(views: list[str] | None = None, objects: list[str] | None = None, shading: str = "solid",
                 zoom: float = 1.0, instance_id: str = "",
                 workspace_id: str = "") -> list[TextContent | ImageContent]:
    """Read-only: LOOK at the open Blender scene — returns rendered images you can see.

    Use it after every blender_execute to check the shape instead of trusting your code.
    views (max 4): the presets 'overview' (high 3/4), 'front' (from -Y), 'side' (from +X), 'back',
    'top', 'camera' (the scene's active camera) — OR any angle as "<azimuth>/<elevation>" in
    degrees, e.g. "120/25" or "-45/60" (azimuth 0 = front, 90 = right; elevation -89..89). Reach
    for a custom angle whenever a detail hides behind a face in all six presets.
    Views auto-frame all visible geometry, or only the named `objects` — naming the part you just
    built is the cheapest way to get close to it.
    zoom (0.2–8, default 1): >1 moves in, <1 pulls back. A detail that is a few pixels wide at
    zoom 1 looks exactly like a part you never built.
    shading='solid' is fast (≈1 s, studio light + cavity; colour comes from each material's
    Viewport Display colour, so set `mat.diffuse_color` too); 'xray' is see-through — use it to
    check whether two parts actually intersect, or whether there is stray geometry inside, which a
    solid render hides completely; 'rendered' uses EEVEE to show real materials and lights
    (slower). Render settings are restored afterwards.
    """

    data = use_case(
        blender_use_cases.look, workspace_id or default_workspace_id(), views=views or [], objects=objects or [],
        shading=shading, zoom=zoom, instance_id=instance_id,
    )
    return with_images(data)


@tool(effect="confirms", kit="canvas")
def blender_execute(code: str, purpose: str = "", instance_id: str = "") -> dict[str, Any]:
    """Confirmation required: run Python (bpy) inside the user's open Blender to model.

    This is full Blender: bmesh, modifiers (bevel, subdivision, boolean, array, mirror, solidify),
    curves, geometry nodes, materials (Principled BSDF), lights, cameras. `bpy`, `Vector` and `math`
    are preloaded; print() output comes back as `printed`, and a variable named `output` comes back
    as `output`. If your code raises, you get the traceback — fix it and try again.
    Work in small steps: one part per call, then blender_look to check it. Name objects clearly,
    keep real-world scale in metres, and do not delete or modify objects you did not create unless
    the user asked. An undo step is pushed first, so the user can ⌘Z it in Blender.
    `purpose` is a short phrase shown on the approval card ("凉亭的四根柱子").
    Blender's Python is not a sandbox — it can read and write the user's files — hence approval.
    """
    confirmation = open_card(
        {
            "workspace_id": default_workspace_id(),
            "tool": "blender_execute",
            "requested_by": REQUESTED_BY.get(),
            "payload": {"code": code, "purpose": purpose, "instance_id": instance_id},
        },
    )
    return confirmation_reply(confirmation)


@tool(effect="writes", kit="canvas")
def blender_send_scene(scene_id: str, shot_id: str = "", instance_id: str = "",
                       workspace_id: str = "") -> dict[str, Any]:
    """Send a Mosael 3D scene into Blender, so you can refine it there with real modeling.

    Opens a separate `Mosael · <name>` Blender scene holding the blockout geometry (groups and
    materials kept), every shot as a real Blender camera with its move baked, and the shot you
    name as the active camera. Imported GLB models come along as their own objects. Nothing else
    in the user's Blender project is touched. The scene must be saved first: pass its current
    revision's shot, and if the scene changed meanwhile, re-read it with get_scene and send again.
    Then work with blender_inspect / blender_execute / blender_look, and bring the result back
    with blender_import_to_scene (or the user's 「接收 Blender 修改」 button, which returns
    geometry AND camera moves into this same scene).
    """

    workspace = workspace_id or default_workspace_id()

    def send(db, user):
        scene = scenes.read(db, user, workspace, scene_id)
        return blender_use_cases.send(
            db, user, workspace, scene_id, instance_id=instance_id, revision=scene.revision,
            shot_id=shot_id or scene.content["shots"][0]["id"],
        )

    return use_case(send)


@tool(effect="writes", kit="canvas")
def blender_import_to_scene(scene_id: str, base_revision: int, name: str = "", objects: list[str] | None = None,
                            position: list[float] | None = None, instance_id: str = "",
                            workspace_id: str = "") -> dict[str, Any]:
    """Bring what you modeled in Blender into a Mosael 3D scene as ONE model object.

    Exports the open Blender scene — or only the named `objects` (with their children) — as GLB and
    adds it to the scene at `position` ([x,y,z] metres, Mosael is Y-up; default origin). base_revision
    must be the scene's current revision (get_scene). Returns object_id / model_id / new revision.
    Afterwards arrange it with edit_scene and check with view_scene, which now draws imported models
    too — so the frame shows the prop in place among the blockout. Keep the mesh under the renderer's
    triangle budget (decimate in Blender before exporting); view_scene says so in model_warnings when
    it cannot draw one. blender_look still judges the model itself better (Blender's own shading).
    """

    return use_case(
        blender_use_cases.import_to_scene, workspace_id or default_workspace_id(), scene_id, base_revision=base_revision,
        name=name, objects=objects or [], position=position, instance_id=instance_id,
    )


@tool(effect="writes", kit="canvas")
def render_scene_references(scene_id: str, shot_id: str, render: str = "stills", project_id: str = "",
                            workspace_id: str = "") -> dict[str, Any]:
    """Render blockout references of one shot of a 3D scene and save them as assets:
    render='stills' (first + last frame, ~2 s), 'video' (the camera move as an MP4, ~30 s for 5 s),
    or 'both'. Returns first_frame_asset_id / last_frame_asset_id / video_asset_id (empty when not
    rendered), camera_move (camera language computed from the camera path — lens, height,
    dolly/pan/orbit — ready to paste into a generation prompt). Imported models are rendered;
    skipped_models / model_warnings report any that could not be (compressed mesh, over the triangle
    budget, missing file) — check them before trusting the frame. Rendered locally, free. Use the frames as reference_image or
    first_frame/last_frame, and the video as reference_video, for generate_image / generate_video."""

    return use_case(
        scenes_use_cases.render_references, workspace_id or default_workspace_id(), scene_id, shot_id,
        render=render, project_id=project_id or None, out=SceneReferenceOut,
    )
