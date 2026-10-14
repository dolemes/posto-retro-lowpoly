"""Assa os materiais procedurais em texturas (cor difusa) e exporta GLB para Sketchfab.
Uso: blender -b cena.blend --python export_glb_textured.py -- saida.glb"""
import math
import sys

import bpy

out = sys.argv[sys.argv.index("--") + 1]
scene = bpy.context.scene
for o in list(bpy.data.objects):
    if o.name.startswith("Light_Cones") or o.type == 'LIGHT':   # cones falsos/luzes não exportam
        bpy.data.objects.remove(o, do_unlink=True)

scene.render.engine = 'CYCLES'
scene.cycles.device = 'CPU'
scene.cycles.samples = 4
bk = scene.render.bake
bk.use_pass_direct = bk.use_pass_indirect = False
bk.use_pass_color = True
bk.margin = 8
SIZES = {"Terrain_Block": 4096, "Asphalt_Concrete": 4096}

for obj in [o for o in bpy.data.objects if o.type == 'MESH']:
    # materiais exclusivos por objeto (a textura assada é por objeto)
    saved = {}
    for i, slot in enumerate(obj.material_slots):
        m = slot.material.copy()
        bsdf = next(n for n in m.node_tree.nodes if n.type == 'BSDF_PRINCIPLED')
        saved[m.name] = {k: (tuple(bsdf.inputs[k].default_value) if k == "Emission Color" else float(bsdf.inputs[k].default_value)) for k in
                         ("Roughness", "Metallic", "Emission Color", "Emission Strength") if k in bsdf.inputs}
        slot.material = m
    if not obj.data.uv_layers:
        obj.data.uv_layers.new(name="UVMap")
    bpy.ops.object.select_all(action='DESELECT')
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    bpy.ops.object.mode_set(mode='EDIT')
    bpy.ops.mesh.select_all(action='SELECT')
    bpy.ops.uv.smart_project(angle_limit=math.radians(66), island_margin=0.004)
    bpy.ops.object.mode_set(mode='OBJECT')

    size = SIZES.get(obj.name, 2048)
    img = bpy.data.images.new(obj.name + "_Color", size, size)
    for slot in obj.material_slots:
        nt = slot.material.node_tree
        tex = nt.nodes.new("ShaderNodeTexImage")
        tex.image = img
        nt.nodes.active = tex
    bpy.ops.object.bake(type='DIFFUSE')
    img.pack()

    # reconstrói cada material: textura assada -> Base Color; emissão/rugosidade preservadas
    for slot in obj.material_slots:
        m = slot.material
        nt = m.node_tree
        nt.nodes.clear()
        bsdf = nt.nodes.new("ShaderNodeBsdfPrincipled")
        outn = nt.nodes.new("ShaderNodeOutputMaterial")
        tex = nt.nodes.new("ShaderNodeTexImage")
        tex.image = img
        nt.links.new(tex.outputs["Color"], bsdf.inputs["Base Color"])
        nt.links.new(bsdf.outputs["BSDF"], outn.inputs["Surface"])
        for k, v in saved[m.name].items():
            bsdf.inputs[k].default_value = v
        if saved[m.name].get("Emission Strength", 0) > 0:
            nt.links.new(tex.outputs["Color"], bsdf.inputs["Emission Color"])
    print("baked", obj.name, size)

bpy.ops.export_scene.gltf(filepath=out, export_format='GLB', export_apply=True, export_lights=False,
                          export_cameras=False, export_yup=True, export_image_format='JPEG',
                          export_jpeg_quality=90)
