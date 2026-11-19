"""
Coleccionista 3D - Juego básico para Blender
=============================================
Controles:
  WASD o flechas  -> Mover jugador
  R               -> Reiniciar partida
  ESC             -> Salir del juego

Cómo jugar:
  1. Abre Blender
  2. Ve a Scripting (pestaña superior)
  3. Abre este archivo o pégalo en el editor de texto
  4. Pulsa "Run Script" (▶)
  5. Haz clic en la ventana 3D Viewport para capturar el teclado
"""

import bpy
import blf
import gpu
import math
import random
from gpu_extras.batch import batch_for_shader

# ── Configuración ──────────────────────────────────────────────
PLAYER_SPEED = 0.12
COLLECT_RADIUS = 0.9
NUM_COINS = 8
ARENA_SIZE = 9.0

# ── Estado global del juego ──────────────────────────────────────
_game = {
    "running": False,
    "score": 0,
    "total": NUM_COINS,
    "keys": set(),
    "player": None,
    "coins": [],
    "message": "",
    "draw_handle": None,
    "modal_op": None,
}


# ── Utilidades de escena ─────────────────────────────────────────
def _clear_scene():
    bpy.ops.object.select_all(action="SELECT")
    bpy.ops.object.delete(use_global=False)
    for block in bpy.data.meshes:
        if block.users == 0:
            bpy.data.meshes.remove(block)
    for block in bpy.data.materials:
        if block.users == 0:
            bpy.data.materials.remove(block)


def _make_material(name, color, metallic=0.0, roughness=0.5):
    mat = bpy.data.materials.new(name=name)
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes.get("Principled BSDF")
    if bsdf:
        bsdf.inputs["Base Color"].default_value = (*color, 1.0)
        bsdf.inputs["Metallic"].default_value = metallic
        bsdf.inputs["Roughness"].default_value = roughness
    return mat


def _add_box(name, size, location, mat, collection=None):
    bpy.ops.mesh.primitive_cube_add(size=size, location=location)
    obj = bpy.context.active_object
    obj.name = name
    obj.data.materials.append(mat)
    if collection:
        collection.objects.link(obj)
        for col in obj.users_collection:
            if col != collection:
                col.objects.unlink(obj)
    return obj


def _add_sphere(name, radius, location, mat):
    bpy.ops.mesh.primitive_uv_sphere_add(radius=radius, location=location)
    obj = bpy.context.active_object
    obj.name = name
    obj.data.materials.append(mat)
    return obj


def _add_plane(name, size, location, mat):
    bpy.ops.mesh.primitive_plane_add(size=size, location=location)
    obj = bpy.context.active_object
    obj.name = name
    obj.data.materials.append(mat)
    return obj


def _setup_lighting():
    bpy.ops.object.light_add(type="SUN", location=(5, -5, 12))
    sun = bpy.context.active_object
    sun.data.energy = 3.0
    sun.rotation_euler = (math.radians(50), 0, math.radians(30))

    bpy.ops.object.light_add(type="AREA", location=(-4, 4, 6))
    fill = bpy.context.active_object
    fill.data.energy = 150
    fill.data.size = 4


def _random_coin_position(existing):
    for _ in range(50):
        x = random.uniform(-ARENA_SIZE, ARENA_SIZE)
        y = random.uniform(-ARENA_SIZE, ARENA_SIZE)
        pos = (x, y, 0.5)
        ok = True
        for p in existing:
            if math.dist(pos[:2], p[:2]) < 1.5:
                ok = False
                break
        if ok:
            return pos
    return (random.uniform(-5, 5), random.uniform(-5, 5), 0.5)


def _build_scene():
    _clear_scene()

    scene = bpy.context.scene
    scene.render.engine = "BLENDER_EEVEE"

    mat_floor = _make_material("Suelo", (0.15, 0.55, 0.2), roughness=0.8)
    mat_player = _make_material("Jugador", (0.1, 0.4, 0.95), metallic=0.3, roughness=0.3)
    mat_coin = _make_material("Moneda", (1.0, 0.78, 0.1), metallic=0.9, roughness=0.2)
    mat_wall = _make_material("Pared", (0.35, 0.35, 0.4), roughness=0.9)

    _add_plane("Suelo", ARENA_SIZE * 2.4, (0, 0, 0), mat_floor)
    _setup_lighting()

    wall_h = 1.0
    for name, loc, scale in [
        ("Pared_N", (0, ARENA_SIZE + 0.5, wall_h / 2), (ARENA_SIZE * 2 + 1, 0.5, wall_h)),
        ("Pared_S", (0, -ARENA_SIZE - 0.5, wall_h / 2), (ARENA_SIZE * 2 + 1, 0.5, wall_h)),
        ("Pared_E", (ARENA_SIZE + 0.5, 0, wall_h / 2), (0.5, ARENA_SIZE * 2 + 1, wall_h)),
        ("Pared_O", (-ARENA_SIZE - 0.5, 0, wall_h / 2), (0.5, ARENA_SIZE * 2 + 1, wall_h)),
    ]:
        bpy.ops.mesh.primitive_cube_add(location=loc)
        wall = bpy.context.active_object
        wall.name = name
        wall.scale = scale
        wall.data.materials.append(mat_wall)
        bpy.ops.object.transform_apply(scale=True)

    player = _add_box("Jugador", 1.0, (0, 0, 0.5), mat_player)

    coins = []
    positions = []
    for i in range(NUM_COINS):
        pos = _random_coin_position(positions)
        positions.append(pos)
        coin = _add_sphere(f"Moneda_{i + 1}", 0.35, pos, mat_coin)
        coins.append(coin)

    cam_data = bpy.data.cameras.new("CamaraJuego")
    cam_data.lens = 35
    cam = bpy.data.objects.new("CamaraJuego", cam_data)
    bpy.context.collection.objects.link(cam)
    cam.location = (0, -14, 10)
    cam.rotation_euler = (math.radians(55), 0, 0)
    scene.camera = cam

    return player, coins


# ── Lógica del juego ─────────────────────────────────────────────
def _clamp_player(pos):
    limit = ARENA_SIZE - 0.6
    pos.x = max(-limit, min(limit, pos.x))
    pos.y = max(-limit, min(limit, pos.y))
    pos.z = 0.5


def _update_player():
    player = _game["player"]
    if not player:
        return

    dx = dy = 0.0
    keys = _game["keys"]
    if "W" in keys or "UP_ARROW" in keys:
        dy += 1
    if "S" in keys or "DOWN_ARROW" in keys:
        dy -= 1
    if "A" in keys or "LEFT_ARROW" in keys:
        dx -= 1
    if "D" in keys or "RIGHT_ARROW" in keys:
        dx += 1

    if dx or dy:
        length = math.sqrt(dx * dx + dy * dy)
        dx /= length
        dy /= length
        player.location.x += dx * PLAYER_SPEED
        player.location.y += dy * PLAYER_SPEED
        _clamp_player(player.location)


def _animate_coins():
    t = bpy.context.scene.frame_current / 24.0
    for i, coin in enumerate(_game["coins"]):
        if coin and coin.name in bpy.data.objects:
            base_z = 0.5
            coin.location.z = base_z + math.sin(t * 3 + i) * 0.15
            coin.rotation_euler.z = t * 2 + i


def _check_collisions():
    player = _game["player"]
    if not player:
        return

    px, py = player.location.x, player.location.y
    remaining = []

    for coin in _game["coins"]:
        if coin is None or coin.name not in bpy.data.objects:
            continue
        cx, cy = coin.location.x, coin.location.y
        if math.dist((px, py), (cx, cy)) < COLLECT_RADIUS:
            bpy.data.objects.remove(coin, do_unlink=True)
            _game["score"] += 1
        else:
            remaining.append(coin)

    _game["coins"] = remaining

    if _game["score"] >= _game["total"]:
        _game["message"] = "¡GANASTE! Pulsa R para jugar de nuevo"
        _game["running"] = False


def _reset_game():
    player, coins = _build_scene()
    _game["player"] = player
    _game["coins"] = coins
    _game["score"] = 0
    _game["total"] = NUM_COINS
    _game["message"] = ""
    _game["running"] = True
    _game["keys"].clear()


# ── HUD en pantalla ──────────────────────────────────────────────
def _draw_hud():
    region = bpy.context.region
    if not region:
        return

    font_id = 0
    blf.size(font_id, 22)
    blf.color(font_id, 1, 1, 1, 1)

    lines = [
        "COLECCIONISTA 3D",
        f"Monedas: {_game['score']} / {_game['total']}",
        "WASD / Flechas = Mover  |  R = Reiniciar  |  ESC = Salir",
    ]
    if _game["message"]:
        lines.append(_game["message"])

    y = region.height - 30
    for line in lines:
        blf.position(font_id, 20, y, 0)
        blf.draw(font_id, line)
        y -= 28

    # Barra de progreso
    if _game["total"] > 0:
        progress = _game["score"] / _game["total"]
        bar_x, bar_y = 20, 50
        bar_w, bar_h = 200, 12
        shader = gpu.shader.from_builtin("UNIFORM_COLOR")
        batch = batch_for_shader(
            shader, "TRI_FAN",
            {"pos": [(bar_x, bar_y), (bar_x + bar_w, bar_y),
                      (bar_x + bar_w, bar_y + bar_h), (bar_x, bar_y + bar_h)]},
        )
        gpu.state.blend_set("ALPHA")
        shader.bind()
        shader.uniform_float("color", (0.2, 0.2, 0.2, 0.7))
        batch.draw(shader)

        fill_w = bar_w * progress
        if fill_w > 0:
            batch_fill = batch_for_shader(
                shader, "TRI_FAN",
                {"pos": [(bar_x, bar_y), (bar_x + fill_w, bar_y),
                          (bar_x + fill_w, bar_y + bar_h), (bar_x, bar_y + bar_h)]},
            )
            shader.uniform_float("color", (1.0, 0.78, 0.1, 0.9))
            batch_fill.draw(shader)
        gpu.state.blend_set("NONE")


def _start_hud():
    if _game["draw_handle"] is None:
        _game["draw_handle"] = bpy.types.SpaceView3D.draw_handler_add(
            _draw_hud, (), "WINDOW", "POST_PIXEL"
        )


def _stop_hud():
    if _game["draw_handle"] is not None:
        bpy.types.SpaceView3D.draw_handler_remove(_game["draw_handle"], "WINDOW")
        _game["draw_handle"] = None


def _stop_game():
    _game["running"] = False
    _game["keys"].clear()
    _stop_hud()
    if _game["modal_op"]:
        try:
            _game["modal_op"].cancel(bpy.context)
        except Exception:
            pass
        _game["modal_op"] = None
    for area in bpy.context.screen.areas:
        if area.type == "VIEW_3D":
            area.tag_redraw()


# ── Operador modal (bucle del juego) ─────────────────────────────
class GAME_OT_Coleccionista(bpy.types.Operator):
    bl_idname = "game.coleccionista"
    bl_label = "Coleccionista 3D"
    bl_description = "Inicia el juego de coleccionar monedas"

    _timer = None

    def modal(self, context, event):
        if event.type in {"W", "A", "S", "D", "UP_ARROW", "DOWN_ARROW", "LEFT_ARROW", "RIGHT_ARROW"}:
            if event.value == "PRESS":
                _game["keys"].add(event.type)
            elif event.value == "RELEASE":
                _game["keys"].discard(event.type)
            return {"RUNNING_MODAL"}

        if event.type == "TIMER" and _game["running"]:
            _update_player()
            _animate_coins()
            _check_collisions()
            for area in context.screen.areas:
                if area.type == "VIEW_3D":
                    area.tag_redraw()

        if event.type == "R" and event.value == "PRESS":
            _reset_game()
            self.report({"INFO"}, "Partida reiniciada")
            return {"RUNNING_MODAL"}

        if event.type in {"ESC", "RIGHTMOUSE"} and event.value == "PRESS":
            _stop_game()
            self.report({"INFO"}, "Juego terminado")
            return {"CANCELLED"}

        return {"PASS_THROUGH"}

    def invoke(self, context, event):
        if _game["running"]:
            self.report({"WARNING"}, "El juego ya está en marcha")
            return {"CANCELLED"}

        _reset_game()
        _start_hud()
        _game["modal_op"] = self

        wm = context.window_manager
        self._timer = wm.event_timer_add(1.0 / 60.0, window=context.window)
        wm.modal_handler_add(self)

        self.report({"INFO"}, "¡Juego iniciado! Haz clic en el viewport y usa WASD")
        return {"RUNNING_MODAL"}

    def cancel(self, context):
        if self._timer:
            context.window_manager.event_timer_remove(self._timer)
            self._timer = None
        _stop_game()
        return {"CANCELLED"}


# ── Panel en la barra lateral ────────────────────────────────────
class GAME_PT_Panel(bpy.types.Panel):
    bl_label = "Coleccionista 3D"
    bl_idname = "GAME_PT_panel"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Juego"

    def draw(self, context):
        layout = self.layout
        col = layout.column(align=True)
        col.scale_y = 1.4

        if _game["running"]:
            col.label(text=f"Monedas: {_game['score']} / {_game['total']}", icon="FAKE_USER_OFF")
            col.operator("game.coleccionista", text="Reiniciar (o pulsa R)", icon="FILE_REFRESH")
        else:
            col.operator("game.coleccionista", text="▶  JUGAR", icon="PLAY")

        box = col.box()
        box.label(text="Controles:", icon="EVENT_W")
        box.label(text="WASD / Flechas → Mover")
        box.label(text="R → Reiniciar")
        box.label(text="ESC → Salir")


# ── Registro ─────────────────────────────────────────────────────
classes = (GAME_OT_Coleccionista, GAME_PT_Panel)


def register():
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    _stop_game()
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)


if __name__ == "__main__":
    register()
    if not bpy.app.background:
        bpy.ops.game.coleccionista("INVOKE_DEFAULT")