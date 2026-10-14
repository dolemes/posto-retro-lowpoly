"""
Posto de Gasolina Retrô no Deserto (anos 60/70) - diorama isométrico low poly noturno
======================================================================================
Tudo procedural (bmesh + materiais nativos, sem texturas externas), flat shading.

Uso:
    blender --python generate_posto_retro_lowpoly.py
    blender -b --python generate_posto_retro_lowpoly.py -- saida.png [amostras] [resolucao] [CYCLES|EEVEE]

Convenções: unidades em metros, +X = direita, -Y = frente (lado da câmera), +Z = cima.
A câmera ortográfica fica em (+X, -Y, +Z) (isométrica verdadeira). Todas as malhas nascem
com origem em (0,0,0), escala 1 e rotação 0 (coordenadas de objeto = coordenadas de mundo,
usadas pelos materiais procedurais de faixas/estratos).
"""
import math
import random
import sys

import bmesh
import bpy
from mathutils import Matrix, Vector

COLLECTION_NAME = "Posto_Deserto"
SEED = 1971
rng = random.Random(SEED)

HALF = 6.0                       # meia-largura do bloco
ASPHALT = dict(x0=-4.6, x1=4.4, y0=-5.0, y1=1.4)   # pista
APRON = dict(x0=-4.4, x1=4.0, y0=0.5, y1=5.4)      # calçada/pátio de concreto
ASPHALT_TOP, APRON_TOP, ISLAND_TOP = 0.10, 0.18, 0.38
ROOF_BOT = 2.5

SIGN_BASE = Vector((-3.4, -3.8, ASPHALT_TOP))
LAMP_BASE = Vector((3.7, -3.0, ASPHALT_TOP))


# --------------------------------------------------------------------------
# Utilidades gerais
# --------------------------------------------------------------------------
def srgb_to_linear(c):
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def hex_color(h, alpha=1.0):
    h = h.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) / 255.0 for i in (0, 2, 4))
    return (srgb_to_linear(r), srgb_to_linear(g), srgb_to_linear(b), alpha)


def clear_scene():
    for obj in list(bpy.data.objects):
        bpy.data.objects.remove(obj, do_unlink=True)
    for coll in list(bpy.data.collections):
        bpy.data.collections.remove(coll)
    for block in (bpy.data.meshes, bpy.data.materials, bpy.data.lights,
                  bpy.data.cameras, bpy.data.curves):
        for item in list(block):
            block.remove(item)


def new_collection(scene, name):
    coll = bpy.data.collections.new(name)
    scene.collection.children.link(coll)
    return coll


def point_at(obj, target):
    obj.rotation_euler = (Vector(target) - obj.location).to_track_quat('-Z', 'Y').to_euler()


# --------------------------------------------------------------------------
# Materiais
# --------------------------------------------------------------------------
def set_input(node, names, value):
    for name in names:
        if name in node.inputs:
            node.inputs[name].default_value = value
            return


def new_material(name, color, roughness=0.7, specular=0.2, metallic=0.0,
                 emission=None, emission_strength=0.0):
    mat = bpy.data.materials.new(name)
    if not mat.node_tree:
        mat.use_nodes = True
    mat.diffuse_color = color
    bsdf = next(n for n in mat.node_tree.nodes if n.type == 'BSDF_PRINCIPLED')
    set_input(bsdf, ("Base Color",), color)
    set_input(bsdf, ("Roughness",), roughness)
    set_input(bsdf, ("Metallic",), metallic)
    set_input(bsdf, ("Specular IOR Level", "Specular"), specular)
    if emission is not None:
        set_input(bsdf, ("Emission Color", "Emission"), emission)
        set_input(bsdf, ("Emission Strength",), emission_strength)
    return mat, bsdf


def mat_noise(name, hex_a, hex_b, scale=6.0, roughness=0.8, metallic=0.0, lo=0.4, hi=0.6, detail=3.0):
    """Cor com variação procedural (ruído em coordenadas de objeto) entre dois tons."""
    mat, bsdf = new_material(name, hex_color(hex_a), roughness=roughness, metallic=metallic)
    nt = mat.node_tree
    coord = nt.nodes.new("ShaderNodeTexCoord")
    noise = nt.nodes.new("ShaderNodeTexNoise")
    noise.inputs["Scale"].default_value = scale
    noise.inputs["Detail"].default_value = detail
    ramp = nt.nodes.new("ShaderNodeValToRGB")
    ramp.color_ramp.elements[0].position = lo
    ramp.color_ramp.elements[0].color = hex_color(hex_a)
    ramp.color_ramp.elements[1].position = hi
    ramp.color_ramp.elements[1].color = hex_color(hex_b)
    nt.links.new(coord.outputs["Object"], noise.inputs["Vector"])
    nt.links.new(noise.outputs["Fac"], ramp.inputs["Fac"])
    nt.links.new(ramp.outputs["Color"], bsdf.inputs["Base Color"])
    return mat


def mat_emit(name, hex_c, strength, base="#050505"):
    mat, _ = new_material(name, hex_color(base), roughness=0.4, emission=hex_color(hex_c),
                          emission_strength=strength)
    return mat


def mat_bands(name, z_min, z_max, stops, noise_hex=None, roughness=0.9):
    """Faixas horizontais pela altura z (ramp constante) + desgaste por ruído."""
    mat, bsdf = new_material(name, hex_color(stops[0][1]), roughness=roughness)
    nt = mat.node_tree
    coord = nt.nodes.new("ShaderNodeTexCoord")
    sep = nt.nodes.new("ShaderNodeSeparateXYZ")
    rng_n = nt.nodes.new("ShaderNodeMapRange")
    rng_n.inputs["From Min"].default_value = z_min
    rng_n.inputs["From Max"].default_value = z_max
    ramp = nt.nodes.new("ShaderNodeValToRGB")
    ramp.color_ramp.interpolation = 'CONSTANT'
    els = ramp.color_ramp.elements
    while len(els) < len(stops):
        els.new(0.5)
    for el, (pos, col) in zip(els, stops):
        el.position, el.color = pos, hex_color(col)
    nt.links.new(coord.outputs["Object"], sep.inputs["Vector"])
    nt.links.new(sep.outputs["Z"], rng_n.inputs["Value"])
    nt.links.new(rng_n.outputs["Result"], ramp.inputs["Fac"])
    out = ramp.outputs["Color"]
    if noise_hex:                               # sujeira/desgaste: mistura com tom escuro
        noise = nt.nodes.new("ShaderNodeTexNoise")
        noise.inputs["Scale"].default_value = 5.0
        noise.inputs["Detail"].default_value = 4.0
        nt.links.new(coord.outputs["Object"], noise.inputs["Vector"])
        cr = nt.nodes.new("ShaderNodeValToRGB")
        cr.color_ramp.elements[0].position, cr.color_ramp.elements[1].position = 0.45, 0.65
        nt.links.new(noise.outputs["Fac"], cr.inputs["Fac"])
        mix = nt.nodes.new("ShaderNodeMix")
        mix.data_type = 'RGBA'
        mix.inputs["B"].default_value = hex_color(noise_hex)
        nt.links.new(cr.outputs["Color"], mix.inputs["Factor"])
        nt.links.new(out, mix.inputs["A"])
        out = mix.outputs["Result"]
    nt.links.new(out, bsdf.inputs["Base Color"])
    return mat


def mat_strata(name):
    """Estratos de terra pelo z (com ruído deformando as camadas)."""
    mat, bsdf = new_material(name, hex_color("#5A3F2A"), roughness=0.95)
    nt = mat.node_tree
    coord = nt.nodes.new("ShaderNodeTexCoord")
    sep = nt.nodes.new("ShaderNodeSeparateXYZ")
    noise = nt.nodes.new("ShaderNodeTexNoise")
    noise.inputs["Scale"].default_value = 1.6
    add = nt.nodes.new("ShaderNodeMath")
    add.operation = 'ADD'
    mul = nt.nodes.new("ShaderNodeMath")
    mul.operation = 'MULTIPLY'
    mul.inputs[1].default_value = 0.5
    rng_n = nt.nodes.new("ShaderNodeMapRange")
    rng_n.inputs["From Min"].default_value = -3.0
    rng_n.inputs["From Max"].default_value = 0.0
    ramp = nt.nodes.new("ShaderNodeValToRGB")
    ramp.color_ramp.interpolation = 'CONSTANT'
    cols = ["#2B1D14", "#4A2F1F", "#6B4A30", "#8A6A45", "#B08A5A"]
    els = ramp.color_ramp.elements
    while len(els) < len(cols):
        els.new(0.5)
    for i, (el, c) in enumerate(zip(els, cols)):
        el.position = i / len(cols)
        el.color = hex_color(c)
    nt.links.new(coord.outputs["Object"], sep.inputs["Vector"])
    nt.links.new(coord.outputs["Object"], noise.inputs["Vector"])
    nt.links.new(noise.outputs["Fac"], mul.inputs[0])
    nt.links.new(sep.outputs["Z"], add.inputs[0])
    nt.links.new(mul.outputs["Value"], add.inputs[1])
    nt.links.new(add.outputs["Value"], rng_n.inputs["Value"])
    nt.links.new(rng_n.outputs["Result"], ramp.inputs["Fac"])
    nt.links.new(ramp.outputs["Color"], bsdf.inputs["Base Color"])
    return mat


def mat_light_cone(name, hex_c, z_ground, z_lamp, strength):
    """Cone de luz volumétrico falso: transparente + emissão que some nas bordas e no chão."""
    mat = bpy.data.materials.new(name)
    if not mat.node_tree:
        mat.use_nodes = True
    nt = mat.node_tree
    nt.nodes.clear()
    out = nt.nodes.new("ShaderNodeOutputMaterial")
    transp = nt.nodes.new("ShaderNodeBsdfTransparent")
    emit = nt.nodes.new("ShaderNodeEmission")
    emit.inputs["Color"].default_value = hex_color(hex_c)
    emit.inputs["Strength"].default_value = 4.0
    mix = nt.nodes.new("ShaderNodeMixShader")
    fres = nt.nodes.new("ShaderNodeFresnel")
    fres.inputs["IOR"].default_value = 1.6
    inv = nt.nodes.new("ShaderNodeMath")
    inv.operation = 'SUBTRACT'
    inv.inputs[0].default_value = 1.0
    coord = nt.nodes.new("ShaderNodeTexCoord")
    sep = nt.nodes.new("ShaderNodeSeparateXYZ")
    grad = nt.nodes.new("ShaderNodeMapRange")
    grad.inputs["From Min"].default_value = z_ground
    grad.inputs["From Max"].default_value = z_lamp
    prod = nt.nodes.new("ShaderNodeMath")
    prod.operation = 'MULTIPLY'
    k = nt.nodes.new("ShaderNodeMath")
    k.operation = 'MULTIPLY'
    k.inputs[1].default_value = strength
    nt.links.new(fres.outputs["Fac"], inv.inputs[1])
    nt.links.new(coord.outputs["Object"], sep.inputs["Vector"])
    nt.links.new(sep.outputs["Z"], grad.inputs["Value"])
    nt.links.new(inv.outputs["Value"], prod.inputs[0])
    nt.links.new(grad.outputs["Result"], prod.inputs[1])
    nt.links.new(prod.outputs["Value"], k.inputs[0])
    nt.links.new(k.outputs["Value"], mix.inputs["Fac"])
    nt.links.new(transp.outputs["BSDF"], mix.inputs[1])
    nt.links.new(emit.outputs["Emission"], mix.inputs[2])
    nt.links.new(mix.outputs["Shader"], out.inputs["Surface"])
    return mat


def build_materials():
    m = {}
    m["sand"] = mat_noise("Sand", "#6E5A44", "#85705A", scale=3.0, roughness=1.0)
    m["strata"] = mat_strata("Dirt_Strata")
    m["asphalt"] = mat_noise("Asphalt", "#2A2B30", "#3B3C42", scale=9.0, roughness=0.85)
    m["concrete"] = mat_noise("Concrete", "#7C7A74", "#9A978E", scale=5.0, roughness=0.9)
    m["crack"], _ = new_material("Crack", hex_color("#050506"), roughness=1.0)
    m["line"] = mat_noise("Road_Line", "#8A7420", "#3A3326", scale=14.0, roughness=0.9, lo=0.35, hi=0.55)
    m["wall"] = mat_bands("Wall_Bands", 0.18, 2.5, [
        (0.0, "#B5A488"), (0.46, "#D97A2A"), (0.57, "#B02A22"), (0.66, "#B5A488")],
        noise_hex="#5A4F40")
    m["roof"] = mat_noise("Roof_Rust", "#4A2A1C", "#6A3A22", scale=4.0, roughness=0.8, metallic=0.4)
    m["fascia_o"] = mat_noise("Fascia_Orange", "#B8631F", "#7A4A2A", scale=7.0, roughness=0.8)
    m["fascia_r"] = mat_noise("Fascia_Red", "#8E221C", "#5A2A22", scale=7.0, roughness=0.8)
    m["rust"] = mat_noise("Rust", "#5A2D16", "#8A4A22", scale=8.0, roughness=0.75, metallic=0.5)
    m["rust_dark"] = mat_noise("Rust_Dark", "#2E1A12", "#5A3018", scale=10.0, roughness=0.8, metallic=0.4)
    m["window"] = mat_emit("Window_Glow", "#FFA24A", 1.6, base="#2A1A0C")
    m["frame"], _ = new_material("Window_Frame", hex_color("#1C1612"), roughness=0.6, metallic=0.3)
    m["pump_red"] = mat_noise("Pump_Red", "#9A1E16", "#6A2A22", scale=9.0, roughness=0.5, metallic=0.2)
    m["pump_blue"] = mat_noise("Pump_Blue", "#1F4C9A", "#2A3A5A", scale=9.0, roughness=0.5, metallic=0.2)
    m["cream"], _ = new_material("Cream", hex_color("#C9BC9A"), roughness=0.6)
    m["globe"] = mat_emit("Pump_Globe", "#FFD890", 2.5, base="#8A7A50")
    m["display"] = mat_emit("Pump_Display", "#9CFFB0", 2.0, base="#0A1A0E")
    m["rubber"], _ = new_material("Rubber", hex_color("#0E0E10"), roughness=0.85)
    m["neon_red"] = mat_emit("Neon_Red", "#FF1E2E", 14.0, base="#400008")
    m["neon_blue"] = mat_emit("Neon_Blue", "#2A6BFF", 14.0, base="#001040")
    m["neon_dead"], _ = new_material("Neon_Dead", hex_color("#3A2A2E"), roughness=0.4)
    m["bulb"] = mat_emit("Bulb", "#FFC070", 4.0, base="#403018")
    m["lamp"] = mat_emit("Lamp_Head", "#FFB555", 20.0, base="#302010")
    m["fixture"] = mat_emit("Canopy_Fixture", "#FFB866", 8.0, base="#302010")
    m["cactus"] = mat_noise("Cactus", "#1E4A2A", "#2C6038", scale=14.0, roughness=0.8)
    m["bush"] = mat_noise("Dry_Bush", "#5A4824", "#7A6430", scale=12.0, roughness=1.0)
    m["rock"] = mat_noise("Rock", "#4C4640", "#6A6258", scale=5.0, roughness=0.95)
    m["barrel_a"] = mat_noise("Barrel_Red", "#7A2A1C", "#4A2A20", scale=9.0, roughness=0.6, metallic=0.4)
    m["barrel_b"] = mat_noise("Barrel_Teal", "#1F5A5A", "#2A3A3A", scale=9.0, roughness=0.6, metallic=0.4)
    m["wood"] = mat_noise("Wood", "#5A4028", "#7A5A38", scale=10.0, roughness=0.9)
    m["cone_amber"] = mat_light_cone("Cone_Amber", "#FFB050", 0.15, 4.6, 0.10)
    m["cone_canopy"] = mat_light_cone("Cone_Canopy", "#FFB45A", 0.2, ROOF_BOT, 0.08)
    return m


# --------------------------------------------------------------------------
# Construtor de malhas (bmesh) com flat shading e transformação opcional
# --------------------------------------------------------------------------
class Builder:
    def __init__(self, name, mats):
        self.name, self.bm, self.mats, self.xf = name, bmesh.new(), [], None
        self._idx = {}
        self.mats_in = mats

    def mi(self, key):
        if key not in self._idx:
            self._idx[key] = len(self.mats)
            self.mats.append(self.mats_in[key])
        return self._idx[key]

    def V(self, p):
        p = Vector(p)
        return self.bm.verts.new(self.xf(p) if self.xf else p)

    def face(self, verts, mat):
        f = self.bm.faces.new(verts)
        f.material_index = self.mi(mat)
        return f

    def hexa(self, bot, top, mat):
        """Sólido a partir de dois anéis (mesmo número de pontos, anti-horário visto de cima)."""
        a = [self.V(p) for p in bot]
        b = [self.V(p) for p in top]
        n = len(a)
        self.face(a[::-1], mat)
        self.face(b, mat)
        for i in range(n):
            j = (i + 1) % n
            self.face((a[i], a[j], b[j], b[i]), mat)

    def box(self, c, s, mat, rz=0.0):
        cx, cy, cz = c
        hx, hy, hz = s[0] / 2, s[1] / 2, s[2] / 2
        rot = Matrix.Rotation(rz, 3, 'Z')
        ring = [(-hx, -hy), (hx, -hy), (hx, hy), (-hx, hy)]
        bot = [Vector((cx, cy, cz)) + rot @ Vector((x, y, -hz)) for x, y in ring]
        top = [Vector((cx, cy, cz)) + rot @ Vector((x, y, hz)) for x, y in ring]
        self.hexa(bot, top, mat)

    def tube(self, p0, p1, r0, r1, sides, mat, twist=0.0):
        p0, p1 = Vector(p0), Vector(p1)
        a = (p1 - p0).normalized()
        ref = Vector((0, 0, 1)) if abs(a.z) < 0.9 else Vector((1, 0, 0))
        u = a.cross(ref).normalized()
        v = a.cross(u).normalized()

        def ring(c, r):
            return [self.V(c + (u * math.cos(t) + v * math.sin(t)) * r)
                    for t in ((2 * math.pi * (k + 0.5) / sides + twist) for k in range(sides))]
        ra = ring(p0, r0)
        self.face(ra[::-1], mat)
        if r1 < 0.0005:
            apex = self.V(p1)
            for i in range(sides):
                self.face((ra[i], ra[(i + 1) % sides], apex), mat)
            return
        rb = ring(p1, r1)
        self.face(rb, mat)
        for i in range(sides):
            j = (i + 1) % sides
            self.face((ra[i], ra[j], rb[j], rb[i]), mat)

    def poly_prism(self, pts, z0, z1, mat):
        self.hexa([(x, y, z0) for x, y in pts], [(x, y, z1) for x, y in pts], mat)

    def strip(self, pts, widths, z, mat):
        """Faixa plana (anti-horária visto de cima) ao longo de uma polilinha 2D."""
        left, right = [], []
        for i, p in enumerate(pts):
            a = pts[max(i - 1, 0)]
            b = pts[min(i + 1, len(pts) - 1)]
            d = Vector((b[0] - a[0], b[1] - a[1], 0)).normalized()
            n = Vector((-d.y, d.x, 0)) * (widths[i] / 2)
            left.append(self.V((p[0] + n.x, p[1] + n.y, z)))
            right.append(self.V((p[0] - n.x, p[1] - n.y, z)))
        for i in range(len(pts) - 1):
            self.face((right[i], right[i + 1], left[i + 1], left[i]), mat)

    def blob(self, c, s, jitter, mat, rz=0.0, sub=1):
        """Icosfera achatada/deformada (rochas, arbustos, globos)."""
        ret = bmesh.ops.create_icosphere(self.bm, subdivisions=sub, radius=1.0)
        verts = ret["verts"]
        rot = Matrix.Rotation(rz, 3, 'Z')
        for v in verts:
            q = Vector((v.co.x * s[0], v.co.y * s[1], v.co.z * s[2]))
            q += Vector((rng.uniform(-1, 1), rng.uniform(-1, 1), rng.uniform(-1, 1))) * jitter
            v.co = Vector(c) + rot @ q
            if self.xf:
                v.co = self.xf(v.co)
        idx = self.mi(mat)
        for f in {f for v in verts for f in v.link_faces}:
            f.material_index = idx
        return verts

    def finish(self, coll, recalc=True, shadow=True):
        bm = self.bm
        if recalc:
            bmesh.ops.recalc_face_normals(bm, faces=bm.faces[:])
        for f in bm.faces:
            f.smooth = False
        mesh = bpy.data.meshes.new(self.name + "_Mesh")
        bm.to_mesh(mesh)
        bm.free()
        for mat in self.mats:
            mesh.materials.append(mat)
        obj = bpy.data.objects.new(self.name, mesh)
        coll.objects.link(obj)
        if not shadow:                      # cones de luz falsos: não interagem com a iluminação
            obj.visible_shadow = False
            obj.visible_diffuse = False
            obj.visible_glossy = False
            obj.visible_transmission = False
            obj.visible_volume_scatter = False
        return obj


def jitter_rect(r, step=0.9, amp=0.12):
    """Contorno anti-horário de um retângulo com bordas irregulares."""
    pts = []
    corners = [(r["x0"], r["y0"]), (r["x1"], r["y0"]), (r["x1"], r["y1"]), (r["x0"], r["y1"])]
    for k in range(4):
        (ax, ay), (bx, by) = corners[k], corners[(k + 1) % 4]
        n = max(2, int(math.hypot(bx - ax, by - ay) / step))
        for i in range(n):
            t = i / n
            x, y = ax + (bx - ax) * t, ay + (by - ay) * t
            pts.append((x + rng.uniform(-amp, amp), y + rng.uniform(-amp, amp)))
    return pts


def rect_dist(x, y, r):
    dx = max(r["x0"] - x, 0, x - r["x1"])
    dy = max(r["y0"] - y, 0, y - r["y1"])
    return math.hypot(dx, dy)


# --------------------------------------------------------------------------
# Terreno flutuante + asfalto + concreto
# --------------------------------------------------------------------------
def build_terrain(coll, mats):
    b = Builder("Terrain_Block", mats)
    N = 24
    step = 2 * HALF / N
    grid = {}
    for j in range(N + 1):
        for i in range(N + 1):
            x, y = -HALF + i * step, -HALF + j * step
            edge = i in (0, N) or j in (0, N)
            if not edge:
                x += rng.uniform(-0.15, 0.15)
                y += rng.uniform(-0.15, 0.15)
            d = min(rect_dist(x, y, ASPHALT), rect_dist(x, y, APRON))
            amp = min(max((d - 0.3) / 1.0, 0.0), 1.0) * 0.16
            z = rng.uniform(-0.02, 1.0) * amp
            grid[(i, j)] = b.V((x, y, z))
    for j in range(N):
        for i in range(N):
            b.face((grid[(i, j)], grid[(i + 1, j)], grid[(i + 1, j + 1)], grid[(i, j + 1)]), "sand")
    loop = [(i, 0) for i in range(N)] + [(N, j) for j in range(N)] \
        + [(i, N) for i in range(N, 0, -1)] + [(0, j) for j in range(N, 0, -1)]
    bottom = []
    for (i, j) in loop:
        top = grid[(i, j)].co
        k = 0.66
        bottom.append(b.V((top.x * k + rng.uniform(-0.3, 0.3), top.y * k + rng.uniform(-0.3, 0.3),
                           -2.5 - rng.uniform(0.0, 0.7))))
    n = len(loop)
    for t in range(n):
        u = (t + 1) % n
        b.face((grid[loop[t]], bottom[t], bottom[u], grid[loop[u]]), "strata")
    b.face(bottom[::-1], "strata")
    b.finish(coll)


def build_ground_details(coll, mats):
    b = Builder("Asphalt_Concrete", mats)
    outline = jitter_rect(ASPHALT)
    b.poly_prism(outline, 0.0, ASPHALT_TOP, "asphalt")
    b.poly_prism(jitter_rect(APRON, amp=0.08), 0.0, APRON_TOP, "concrete")
    # ilha de concreto elevada sob as bombas
    b.box((1.85, 1.5, (APRON_TOP + ISLAND_TOP) / 2), (2.5, 1.05, ISLAND_TOP - APRON_TOP), "concrete")
    b.box((-2.1, 2.5, (APRON_TOP + 0.3) / 2), (3.6, 0.5, 0.3 - APRON_TOP), "concrete")   # degrau/calçada da loja
    # linha central tracejada da pista
    for k in range(7):
        x0 = -4.2 + k * 1.3
        b.poly_prism([(x0, -3.05), (x0 + 0.7, -3.05), (x0 + 0.7, -2.93), (x0, -2.93)],
                     ASPHALT_TOP, ASPHALT_TOP + 0.004, "line")
    # rachaduras irregulares (polilinhas aleatórias a partir das bordas)
    zc = ASPHALT_TOP + 0.006

    def crack(x, y, ang, segs, w):
        pts = [(x, y)]
        for _ in range(segs):
            ang += rng.uniform(-0.7, 0.7)
            L = rng.uniform(0.35, 0.8)
            x, y = x + math.cos(ang) * L, y + math.sin(ang) * L
            pts.append((x, y))
        widths = [w * (1 - 0.8 * i / segs) for i in range(len(pts))]
        b.strip(pts, widths, zc, "crack")
        return pts

    starts = [(-4.6, -4.2, 0.2), (-4.6, -1.0, -0.2), (-3.0, -5.0, 1.5), (0.5, -5.0, 1.3),
              (3.5, -5.0, 1.9), (4.4, -3.5, 3.0), (4.4, -0.2, 3.3), (-1.0, -5.0, 1.0)]
    for (sx, sy, a) in starts:
        pts = crack(sx, sy, a, rng.randint(5, 9), rng.uniform(0.06, 0.1))
        if rng.random() < 0.7:
            m = rng.randint(2, len(pts) - 2)
            crack(pts[m][0], pts[m][1], a + rng.choice((-1, 1)) * 0.9, rng.randint(2, 4), 0.045)
    crack(-1.5, -1.8, 0.4, 7, 0.07)           # fissura interna isolada
    crack(2.4, -2.0, 2.4, 6, 0.06)
    # cunhas de terra/areia invadindo as bordas do asfalto
    r = ASPHALT
    for _ in range(26):
        side = rng.choice("nsew")
        t = rng.random()
        if side in "ns":
            x = r["x0"] + t * (r["x1"] - r["x0"])
            y = r["y0"] if side == "s" else r["y1"]
            dx, dy = 0.0, (1 if side == "s" else -1)
        else:
            y = r["y0"] + t * (r["y1"] - r["y0"])
            x = r["x0"] if side == "w" else r["x1"]
            dx, dy = (1 if side == "w" else -1), 0.0
        if side == "n" and APRON["x0"] < x < APRON["x1"]:
            continue
        base = rng.uniform(0.3, 0.7)
        depth = rng.uniform(0.25, 0.9)
        px, py = -dy, dx
        a1 = (x - px * base - dx * 0.25, y - py * base - dy * 0.25)
        a2 = (x + px * base - dx * 0.25, y + py * base - dy * 0.25)
        apex = (x + dx * depth + rng.uniform(-0.15, 0.15), y + dy * depth + rng.uniform(-0.15, 0.15))
        b.poly_prism([a1, a2, apex] if (a2[0] - a1[0]) * (apex[1] - a1[1]) - (a2[1] - a1[1]) * (apex[0] - a1[0]) > 0
                     else [a1, apex, a2], ASPHALT_TOP, ASPHALT_TOP + 0.01, "sand")
    b.finish(coll)


# --------------------------------------------------------------------------
# Edifício + cobertura
# --------------------------------------------------------------------------
BLD = dict(x0=-3.8, x1=-0.4, y0=2.8, y1=5.0)
CANOPY = dict(x0=0.3, x1=3.6, y0=0.9, y1=2.9)       # cobertura sÃ³ sobre as bombas (nÃ£o esconde a loja na vista iso)
BROOF = dict(x0=-4.1, x1=-0.1, y0=2.55, y1=5.3)     # telhado da loja
CANOPY_LIGHTS = ((1.0, 1.5), (2.6, 1.5), (1.9, 2.5))


def add_wedge_roof(b, R, z_front, z_back, fascia=True):
    """Telhado plano em cunha: mais alto atrÃ¡s, com vigas frontal/lateral listradas."""
    ring = [(R["x0"], R["y0"]), (R["x1"], R["y0"]), (R["x1"], R["y1"]), (R["x0"], R["y1"])]
    top_z = [ROOF_BOT + z_front, ROOF_BOT + z_front, ROOF_BOT + z_back, ROOF_BOT + z_back]
    b.hexa([(x, y, ROOF_BOT) for x, y in ring], [(x, y, z) for (x, y), z in zip(ring, top_z)], "roof")
    if not fascia:
        return
    cx, cy = (R["x0"] + R["x1"]) / 2, (R["y0"] + R["y1"]) / 2
    w, d = R["x1"] - R["x0"] + 0.1, R["y1"] - R["y0"]
    b.box((cx, R["y0"] - 0.05, ROOF_BOT + 0.07), (w, 0.1, 0.14), "fascia_o")
    b.box((cx, R["y0"] - 0.05, ROOF_BOT + 0.22), (w, 0.1, 0.12), "fascia_r")
    b.box((R["x1"] + 0.05, cy, ROOF_BOT + 0.07), (0.1, d, 0.14), "fascia_o")
    b.box((R["x1"] + 0.05, cy, ROOF_BOT + 0.22), (0.1, d, 0.12), "fascia_r")


def build_station(coll, mats):
    b = Builder("Gas_Station", mats)
    z0 = APRON_TOP
    B = BLD
    b.box(((B["x0"] + B["x1"]) / 2, (B["y0"] + B["y1"]) / 2, (z0 + ROOF_BOT) / 2),
          (B["x1"] - B["x0"], B["y1"] - B["y0"], ROOF_BOT - z0), "wall")

    add_wedge_roof(b, CANOPY, 0.18, 0.7)
    add_wedge_roof(b, BROOF, 0.15, 0.8)
    b.box((-1.6, 4.4, ROOF_BOT + 1.15), (0.9, 0.7, 0.4), "rust_dark")      # ventilaÃ§Ã£o no telhado
    b.tube((-3.4, 4.7, ROOF_BOT + 0.9), (-3.5, 4.7, ROOF_BOT + 2.3), 0.04, 0.025, 4, "rust_dark")   # antena

    # pilares de metal enferrujados (levemente inclinados)
    C = CANOPY
    for (px, py, lean) in ((C["x0"] + 0.1, C["y0"] + 0.1, 0.05), (C["x1"] - 0.1, C["y0"] + 0.1, -0.06),
                           (C["x1"] - 0.1, C["y1"] - 0.1, 0.0)):
        b.tube((px, py, APRON_TOP), (px + lean, py - lean * 0.5, ROOF_BOT), 0.11, 0.09, 4, "rust", twist=math.pi / 4)
        b.box((px, py, APRON_TOP + 0.05), (0.3, 0.3, 0.1), "rust_dark")
    b.tube((C["x0"] + 0.1, C["y0"] + 0.1, 1.75), (C["x0"] + 0.1, C["y0"] + 0.8, ROOF_BOT), 0.04, 0.04, 4, "rust_dark")
    b.tube((C["x1"] - 0.1, C["y0"] + 0.1, 1.75), (C["x1"] - 0.1, C["y0"] + 0.8, ROOF_BOT), 0.04, 0.04, 4, "rust_dark")
    for px in (-4.0, -0.2):                      # pilares da frente da loja
        b.tube((px, 2.45, APRON_TOP), (px, 2.45, ROOF_BOT), 0.09, 0.08, 4, "rust", twist=math.pi / 4)
    # janelas (vidro com brilho quente fraco) + molduras e travessas
    def window_front(x0, x1, z_a, z_b, mull=True):
        y = B["y0"]
        b.box(((x0 + x1) / 2, y - 0.02, (z_a + z_b) / 2), (x1 - x0 + 0.14, 0.04, z_b - z_a + 0.14), "frame")
        b.box(((x0 + x1) / 2, y - 0.045, (z_a + z_b) / 2), (x1 - x0, 0.03, z_b - z_a), "window")
        if mull:
            b.box(((x0 + x1) / 2, y - 0.06, (z_a + z_b) / 2), (0.06, 0.04, z_b - z_a), "frame")
            b.box(((x0 + x1) / 2, y - 0.06, (z_a + z_b) / 2 + 0.1), (x1 - x0, 0.04, 0.05), "frame")

    window_front(-3.5, -2.3, 0.75, 2.0)
    window_front(-1.35, -0.65, 0.75, 2.0, mull=False)
    # porta
    b.box((-1.8, B["y0"] - 0.02, 1.1), (0.7, 0.05, 1.8), "frame")
    b.box((-1.8, B["y0"] - 0.05, 1.15), (0.5, 0.03, 1.3), "window")
    # janela da lateral direita (visível da câmera)
    xs = B["x1"]
    b.box((xs + 0.02, 3.9, 1.38), (0.04, 1.54, 1.39), "frame")
    b.box((xs + 0.045, 3.9, 1.38), (0.03, 1.4, 1.25), "window")
    b.box((xs + 0.06, 3.9, 1.38), (0.04, 0.06, 1.25), "frame")
    # luminárias sob a cobertura
    for (fx, fy_) in CANOPY_LIGHTS:
        b.box((fx, fy_, ROOF_BOT - 0.04), (0.6, 0.3, 0.08), "fixture")
    for fx in (-3.0, -1.0):                      # luminÃ¡rias do beiral da loja
        b.box((fx, 2.65, ROOF_BOT - 0.04), (0.5, 0.2, 0.08), "fixture")
    # letreiro apagado/antigo acima da porta
    b.box((-1.8, B["y0"] - 0.03, 2.2), (1.3, 0.05, 0.2), "frame")
    b.box((-2.2, B["y0"] - 0.06, 2.2), (0.35, 0.03, 0.12), "bulb")
    b.finish(coll)


# --------------------------------------------------------------------------
# Bombas de gasolina
# --------------------------------------------------------------------------
def build_pumps(coll, mats):
    b = Builder("Gas_Pumps", mats)
    for (px, py, key) in ((1.2, 1.5, "pump_red"), (2.5, 1.5, "pump_blue")):
        z0 = ISLAND_TOP
        b.hexa([(px - 0.31, py - 0.24, z0), (px + 0.31, py - 0.24, z0), (px + 0.31, py + 0.24, z0), (px - 0.31, py + 0.24, z0)],
               [(px - 0.25, py - 0.2, z0 + 1.15), (px + 0.25, py - 0.2, z0 + 1.15),
                (px + 0.25, py + 0.2, z0 + 1.15), (px - 0.25, py + 0.2, z0 + 1.15)], key)
        b.box((px, py, z0 + 0.5), (0.66, 0.5, 0.08), "cream")            # faixa creme
        b.box((px, py, z0 + 1.2), (0.6, 0.46, 0.2), "rust_dark")          # cabeçote
        b.box((px, py - 0.235, z0 + 0.82), (0.34, 0.03, 0.2), "display")  # visor
        b.box((px, py - 0.225, z0 + 0.6), (0.4, 0.02, 0.1), "cream")
        b.tube((px, py, z0 + 1.3), (px, py, z0 + 1.45), 0.07, 0.07, 6, "rust_dark")
        b.blob((px, py, z0 + 1.68), (0.24, 0.24, 0.24), 0.0, "globe")      # globo
        # holster + mangueira
        b.box((px + 0.31, py, z0 + 0.85), (0.08, 0.2, 0.3), "rust_dark")
        hose = [(px + 0.33, py, z0 + 0.9), (px + 0.5, py + 0.1, z0 + 0.5), (px + 0.45, py - 0.15, z0 + 0.15),
                (px + 0.15, py - 0.45, z0 + 0.03), (px - 0.1, py - 0.38, z0 + 0.03)]
        for p, q in zip(hose, hose[1:]):
            b.tube(p, q, 0.028, 0.028, 4, "rubber")
        b.box((px - 0.12, py - 0.38, z0 + 0.06), (0.16, 0.06, 0.1), "rust_dark")   # bico
    b.finish(coll)


# --------------------------------------------------------------------------
# Placa GAS (torta, enferrujada, neon com falhas)
# --------------------------------------------------------------------------
LETTERS = {
    "G": [(1, .8), (.8, 1), (.2, 1), (0, .8), (0, .2), (.2, 0), (.8, 0), (1, .2), (1, .5), (.55, .5)],
    "A": [(0, 0), (.5, 1), (1, 0)],
    "A2": [(.2, .38), (.8, .38)],
    "S": [(1, .85), (.85, 1), (.15, 1), (0, .85), (0, .65), (.15, .5), (.85, .5), (1, .35),
          (1, .15), (.85, 0), (.15, 0), (0, .15)],
}


def build_sign(coll, mats):
    b = Builder("Gas_Sign", mats)
    tilt = math.radians(-5.0)
    rot_tilt = Matrix.Rotation(tilt, 3, 'Y')
    rot_view = Matrix.Rotation(math.radians(45.0), 3, 'Z')
    # coordenadas locais (u, y, z): u = direita na tela, y>0 = afasta da câmera
    b.xf = lambda p: SIGN_BASE + rot_view @ (rot_tilt @ p)

    b.box((0, 0.5, 0.05), (1.0, 0.9, 0.5), "concrete")                       # sapata
    b.tube((0, 0.3, 0.2), (0, 0.3, 4.4), 0.13, 0.11, 4, "rust", twist=math.pi / 4)  # poste
    b.tube((-0.9, 0.35, 0.3), (0, 0.3, 2.2), 0.04, 0.04, 4, "rust_dark")     # escora diagonal
    # corpo da placa
    b.box((0, 0.0, 4.95), (3.5, 0.2, 1.55), "rust_dark")
    b.box((0, -0.115, 4.95), (3.3, 0.04, 1.35), "rust")
    for sx in (-1.7, 1.7):
        b.box((sx, -0.06, 4.95), (0.12, 0.3, 1.62), "rust_dark")
    b.box((0, -0.06, 5.76), (3.5, 0.3, 0.12), "rust_dark")
    b.box((0, -0.06, 4.14), (3.5, 0.3, 0.12), "rust_dark")
    # letras em neon: (letra, cor, índice do segmento apagado)
    spec = [("G", "neon_red", {3, 7}), ("A", "neon_blue", {1}), ("S", "neon_red", {5, 6})]
    lw, gap = 0.85, 0.3
    u0 = -(3 * lw + 2 * gap) / 2
    for li, (ch, mat, dead) in enumerate(spec):
        ox = u0 + li * (lw + gap)
        strokes = [(LETTERS[ch], dead)]
        if ch == "A":
            strokes.append((LETTERS["A2"], set()))
        for pts, ded in strokes:
            P = [(ox + x * lw, -0.2, 4.45 + y * 1.0) for x, y in pts]
            for k, (p, q) in enumerate(zip(P, P[1:])):
                b.tube(p, q, 0.04, 0.04, 4, "neon_dead" if k in ded else mat, twist=math.pi / 4)
                b.box(p, (0.07, 0.07, 0.07), "neon_dead" if k in ded else mat)
            # suportes do tubo
            for p in P[::3]:
                b.tube((p[0], p[1], p[2]), (p[0], -0.11, p[2]), 0.012, 0.012, 4, "rust_dark")
    # seta retrô no topo
    arrow = [(-1.7, 6.25), (-0.8, 6.75), (-0.8, 6.5), (1.5, 6.5), (1.5, 6.0), (-0.8, 6.0), (-0.8, 5.75)]
    # a seta é côncava: cabeça e haste viram dois sólidos convexos
    head = [(-1.7, 6.25), (-0.8, 6.75), (-0.8, 5.75)]
    b.hexa([(x, 0.08, z) for x, z in head], [(x, -0.08, z) for x, z in head], "rust")
    shaft = [(-0.8, 6.0), (1.5, 6.0), (1.5, 6.5), (-0.8, 6.5)]
    b.hexa([(x, 0.08, z) for x, z in shaft], [(x, -0.08, z) for x, z in shaft], "rust")
    b.tube((0.2, 0.1, 5.7), (0.2, 0.1, 6.0), 0.05, 0.05, 4, "rust_dark")
    b.tube((-0.9, 0.1, 5.7), (-0.9, 0.1, 6.0), 0.05, 0.05, 4, "rust_dark")
    outline = arrow + [arrow[0]]
    for k, (p, q) in enumerate(zip(outline, outline[1:])):
        mat = "neon_dead" if k in (2, 5) else ("neon_red" if k % 2 == 0 else "neon_blue")
        b.tube((p[0], -0.14, p[1]), (q[0], -0.14, q[1]), 0.035, 0.035, 4, mat, twist=math.pi / 4)
    for x in (-1.2, -0.4, 0.4, 1.2):   # lâmpadas na seta
        b.box((x, -0.12, 6.25), (0.1, 0.06, 0.1), "bulb")
    b.finish(coll)


# --------------------------------------------------------------------------
# Poste de luz + cones de luz falsos
# --------------------------------------------------------------------------
LAMP_HEAD = LAMP_BASE + Vector((-1.0, 0.0, 4.55 - ASPHALT_TOP))


def build_lamp(coll, mats):
    b = Builder("Street_Lamp", mats)
    base = LAMP_BASE
    b.box((base.x, base.y, base.z + 0.15), (0.45, 0.45, 0.3), "concrete")
    b.tube((base.x, base.y, base.z + 0.3), (base.x, base.y, 4.55), 0.1, 0.07, 6, "rust_dark")
    b.tube((base.x, base.y, 4.55), (LAMP_HEAD.x + 0.1, LAMP_HEAD.y, 4.7), 0.05, 0.05, 4, "rust_dark")
    b.box((LAMP_HEAD.x, LAMP_HEAD.y, 4.66), (0.6, 0.32, 0.08), "rust_dark")
    b.box((LAMP_HEAD.x, LAMP_HEAD.y, 4.6), (0.5, 0.26, 0.05), "lamp")
    b.finish(coll)


def build_cones(coll, mats):
    b = Builder("Light_Cones", mats)
    # poste de luz
    apex = Vector((LAMP_HEAD.x, LAMP_HEAD.y, 4.58))
    gnd = Vector((apex.x, apex.y, 0.12))
    b.tube(apex, gnd, 0.1, 2.2, 8, "cone_amber")
    # focos sob a cobertura
    for (fx, fy) in CANOPY_LIGHTS:
        b.tube((fx, fy, ROOF_BOT - 0.08), (fx, fy, 0.25), 0.25, 1.2, 8, "cone_canopy")
    b.finish(coll, recalc=False, shadow=False)


# --------------------------------------------------------------------------
# Vegetação, rochas e detritos
# --------------------------------------------------------------------------
def saguaro(b, x, y, h, r, arms):
    z0 = -0.02
    b.tube((x, y, z0), (x, y, h), r, r * 0.88, 6, "cactus")
    b.tube((x, y, h), (x, y, h + r * 1.1), r * 0.88, 0.0, 6, "cactus")
    for (az, ang, out, up) in arms:
        ax, ay = math.cos(ang), math.sin(ang)
        sx, sy = x + ax * r * 0.4, y + ay * r * 0.4
        ex, ey = x + ax * (r + out), y + ay * (r + out)
        ra = r * 0.62
        zz = h * az
        b.tube((sx, sy, zz), (ex, ey, zz), ra, ra, 6, "cactus")
        b.tube((ex, ey, zz - ra), (ex, ey, zz + up), ra, ra * 0.9, 6, "cactus")
        b.tube((ex, ey, zz + up), (ex, ey, zz + up + ra * 1.1), ra * 0.9, 0.0, 6, "cactus")


def build_props(coll, mats):
    b = Builder("Desert_Props", mats)
    # cactos saguaro
    saguaro(b, 5.0, 3.4, 3.4, 0.28, [(0.55, 0.2, 0.55, 1.0), (0.4, math.pi + 0.3, 0.5, 0.8)])
    saguaro(b, -5.1, -1.6, 2.1, 0.2, [(0.5, -0.3, 0.4, 0.6)])
    saguaro(b, 5.2, -4.4, 1.5, 0.16, [])
    saguaro(b, -5.0, 4.2, 2.6, 0.22, [(0.6, 0.0, 0.45, 0.9)])
    # arbustos secos
    for (x, y) in ((4.8, 0.6), (-5.2, 1.6), (5.4, 5.0), (-3.0, -5.5), (5.0, -3.0), (-5.4, 5.3),
                   (4.7, 4.6), (1.5, 5.7), (-5.0, -4.6)):
        s = rng.uniform(0.28, 0.5)
        b.blob((x, y, 0.1 + s * 0.3), (s, s * 1.1, s * 0.55), 0.06, "bush", rz=rng.uniform(0, 3), sub=1)
    # rochas angulares
    rocks = ((5.4, 1.8, 0.5), (-5.3, -3.2, 0.45), (4.9, -5.1, 0.35), (-5.2, 3.0, 0.3), (5.1, 4.5, 0.55),
             (-3.6, 5.7, 0.4), (0.6, -5.5, 0.3), (-5.5, 0.4, 0.28), (3.0, 5.7, 0.35))
    for (x, y, s) in rocks:
        b.blob((x, y, s * 0.35), (s, s * rng.uniform(0.7, 1.2), s * 0.7), s * 0.2, "rock", rz=rng.uniform(0, 3), sub=1)
    # detritos pequenos na borda de areia/asfalto
    for _ in range(18):
        x, y = rng.uniform(-5.6, 5.6), rng.uniform(-5.6, 5.6)
        if rect_dist(x, y, ASPHALT) < 0.3 or rect_dist(x, y, APRON) < 0.3:
            s = rng.uniform(0.06, 0.14)
            b.blob((x, y, ASPHALT_TOP + s * 0.5), (s, s, s * 0.6), s * 0.3, "rock", rz=rng.uniform(0, 3), sub=0)
    # barris, pneus e caixotes junto ao prédio
    for (x, y, k) in ((0.35, 4.2, "barrel_a"), (0.85, 4.75, "barrel_b"), (-0.1, 5.2, "barrel_a")):
        b.tube((x, y, APRON_TOP), (x, y, APRON_TOP + 0.85), 0.28, 0.28, 8, k)
        b.tube((x, y, APRON_TOP + 0.4), (x, y, APRON_TOP + 0.46), 0.3, 0.3, 8, "rust_dark")
    b.tube((0.5, 0.0, ASPHALT_TOP), (0.5, 0.0, ASPHALT_TOP + 0.2), 0.36, 0.36, 8, "rubber")     # pneus caídos
    b.tube((0.5, 0.0, ASPHALT_TOP + 0.2), (0.5, 0.0, ASPHALT_TOP + 0.4), 0.36, 0.36, 8, "rubber")
    b.tube((0.8, -0.4, ASPHALT_TOP), (0.8, -0.4, ASPHALT_TOP + 0.2), 0.36, 0.36, 8, "rubber")
    b.box((-0.9, 4.7, APRON_TOP + 0.25), (0.6, 0.6, 0.5), "wood", rz=0.3)
    b.box((-0.85, 4.65, APRON_TOP + 0.65), (0.4, 0.4, 0.3), "wood", rz=0.9)
    b.box((-3.9, 2.35, APRON_TOP + 0.2), (0.5, 0.5, 0.4), "wood", rz=0.2)
    b.box((-2.8, 2.45, APRON_TOP + 0.12), (0.4, 0.3, 0.25), "rust_dark", rz=-0.4)             # lata/caixa velha
    b.finish(coll)


# --------------------------------------------------------------------------
# Iluminação, câmera, mundo e render
# --------------------------------------------------------------------------
def add_light(coll, name, kind, loc, energy, color, target=None, size=0.3, spot_deg=None, blend=0.4):
    data = bpy.data.lights.new(name, kind)
    data.energy, data.color = energy, color
    if kind == 'AREA':
        data.size = size
    elif kind in ('POINT', 'SPOT'):
        data.shadow_soft_size = size
    if kind == 'SPOT':
        data.spot_size = math.radians(spot_deg or 90)
        data.spot_blend = blend
    obj = bpy.data.objects.new(name, data)
    obj.location = loc
    coll.objects.link(obj)
    if target is not None:
        point_at(obj, target)
    return obj


def build_lighting(scene, coll):
    # luar: sol azul fraco para modelar as facetas
    sun = bpy.data.lights.new("Moon", 'SUN')
    sun.energy, sun.color, sun.angle = 2.6, (0.45, 0.58, 1.0), math.radians(4)
    so = bpy.data.objects.new("Moon", sun)
    so.location = (-8, 8, 10)
    coll.objects.link(so)
    point_at(so, (0, 0, 0))
    add_light(coll, "Sky_Fill", 'AREA', (6, -8, 12), 1500, (0.35, 0.5, 1.0), (0, 0, 1), size=10)
    # bolsão âmbar do poste
    add_light(coll, "Lamp_Spot", 'SPOT', (LAMP_HEAD.x, LAMP_HEAD.y, 4.5), 3500, (1.0, 0.62, 0.25),
              (LAMP_HEAD.x, LAMP_HEAD.y, 0), size=0.15, spot_deg=70, blend=0.5)
    # focos sob a cobertura
    for i, (fx, fy) in enumerate(CANOPY_LIGHTS):
        add_light(coll, f"Canopy_Spot_{i}", 'SPOT', (fx, fy, ROOF_BOT - 0.12), 1500, (1.0, 0.68, 0.32),
                  (fx, fy, 0), size=0.2, spot_deg=75, blend=0.5)
    # luz vazando das janelas
    add_light(coll, "Window_Front_A", 'SPOT', (-2.9, 2.6, 1.4), 500, (1.0, 0.6, 0.25),
              (-2.9, -2.0, 0.2), size=0.4, spot_deg=100, blend=0.6)
    add_light(coll, "Window_Front_B", 'SPOT', (-1.0, 2.6, 1.4), 300, (1.0, 0.6, 0.25),
              (-1.0, -2.0, 0.2), size=0.3, spot_deg=100, blend=0.6)
    add_light(coll, "Window_Side", 'SPOT', (-0.2, 3.9, 1.4), 300, (1.0, 0.6, 0.25),
              (4.0, 3.9, 0.2), size=0.3, spot_deg=100, blend=0.6)
    # neon da placa
    sb = SIGN_BASE
    add_light(coll, "Neon_Red_Glow", 'POINT', (sb.x - 0.6, sb.y - 1.2, 5.2), 600, (1.0, 0.1, 0.15), size=0.4)
    add_light(coll, "Neon_Blue_Glow", 'POINT', (sb.x + 0.3, sb.y - 1.2, 5.0), 500, (0.15, 0.4, 1.0), size=0.4)
    add_light(coll, "Neon_Ground", 'SPOT', (sb.x - 0.6, sb.y - 0.8, 4.4), 900, (1.0, 0.2, 0.3),
              (sb.x - 1.6, sb.y - 2.4, 0.1), size=0.3, spot_deg=80, blend=0.6)


def build_camera(scene, coll, target, ortho):
    cam_data = bpy.data.cameras.new("Camera_Iso")
    cam_data.type = 'ORTHO'
    cam_data.ortho_scale = ortho
    cam_data.clip_start, cam_data.clip_end = 0.1, 200.0
    cam = bpy.data.objects.new("Camera_Iso", cam_data)
    cam.location = Vector(target) + Vector((1, -1, 1)) * 30       # iso verdadeira: elevação 35,264°
    coll.objects.link(cam)
    point_at(cam, target)
    scene.camera = cam


def build_world(scene):
    world = bpy.data.worlds.get("Night_World") or bpy.data.worlds.new("Night_World")
    if not world.node_tree:
        world.use_nodes = True
    nt = world.node_tree
    nt.nodes.clear()          # nomes dos nós variam com o idioma da interface
    bg = nt.nodes.new("ShaderNodeBackground")
    out = nt.nodes.new("ShaderNodeOutputWorld")
    nt.links.new(bg.outputs["Background"], out.inputs["Surface"])
    bg.inputs["Color"].default_value = (0.004, 0.011, 0.045, 1.0)
    bg.inputs["Strength"].default_value = 1.0
    scene.world = world


def enable_gpu(scene):
    try:
        prefs = bpy.context.preferences.addons['cycles'].preferences
        for kind in ('OPTIX', 'CUDA', 'HIP', 'METAL', 'ONEAPI'):
            try:
                prefs.compute_device_type = kind
                prefs.get_devices()
                devs = [d for d in prefs.devices if d.type != 'CPU']
                if devs:
                    for d in prefs.devices:
                        d.use = d.type != 'CPU'
                    scene.cycles.device = 'GPU'
                    return kind
            except Exception:
                continue
    except Exception:
        pass
    return None


def configure_render(scene, samples, res, engine):
    scene.render.resolution_x = scene.render.resolution_y = res
    scene.render.resolution_percentage = 100
    if engine == 'EEVEE':
        for eng in ('BLENDER_EEVEE_NEXT', 'BLENDER_EEVEE'):
            try:
                scene.render.engine = eng
                break
            except TypeError:
                continue
    else:
        scene.render.engine = 'CYCLES'
        cy = scene.cycles
        cy.samples = samples
        cy.use_adaptive_sampling = True
        cy.use_denoising = True
        cy.max_bounces = 6
        cy.sample_clamp_indirect = 8.0
        print("GPU:", enable_gpu(scene))
    vs = scene.view_settings
    for t in ('AgX', 'Filmic', 'Standard'):
        try:
            vs.view_transform = t
            break
        except TypeError:
            continue
    try:
        vs.look = 'AgX - Punchy'
    except TypeError:
        pass
    vs.exposure = 0.3


def main():
    scene = bpy.context.scene
    clear_scene()
    scene.unit_settings.system = 'METRIC'
    model = new_collection(scene, COLLECTION_NAME)
    studio = new_collection(scene, "Studio_Setup")
    mats = build_materials()

    build_terrain(model, mats)
    build_ground_details(model, mats)
    build_station(model, mats)
    build_pumps(model, mats)
    build_sign(model, mats)
    build_lamp(model, mats)
    build_props(model, mats)
    build_cones(model, mats)

    build_lighting(scene, studio)
    build_camera(scene, studio, target=(-0.2, 0.0, 0.9), ortho=16.5)
    build_world(scene)

    args = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else []
    samples = int(args[1]) if len(args) > 1 else 128
    res = int(args[2]) if len(args) > 2 else 1600
    engine = args[3].upper() if len(args) > 3 else 'CYCLES'
    configure_render(scene, samples, res, engine)
    if args:
        scene.render.filepath = args[0]
        bpy.ops.render.render(write_still=True)
        bpy.ops.wm.save_as_mainfile(filepath=args[0].rsplit(".", 1)[0] + ".blend")
    print("Posto retrô gerado: %d objetos em '%s'" % (len(model.objects), COLLECTION_NAME))


if __name__ == "__main__":
    main()
