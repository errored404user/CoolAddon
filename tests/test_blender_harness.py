"""End-to-end proof that the headless Blender harness really executes Blender.

These are not mocks: every check runs inside the genuine `bpy` 4.5 interpreter,
so an addon that would fail in Blender fails here too.
"""

from __future__ import annotations

import pytest

from blender_runner import assert_checks, blender_version, run_in_blender

pytestmark = pytest.mark.blender


def test_blender_reports_its_version() -> None:
    version = blender_version()
    assert version.startswith("4.5"), f"expected Blender 4.5.x, got {version}"


def test_addon_classes_register_and_run() -> None:
    results = run_in_blender(
        """
        class PROOF_OT_make(bpy.types.Operator):
            bl_idname = "proof.make"
            bl_label = "Make"
            count: bpy.props.IntProperty(default=2)

            def execute(self, context):
                for i in range(self.count):
                    bpy.ops.mesh.primitive_cube_add(location=(i * 2.0, 0, 0))
                return {'FINISHED'}

        class PROOF_PT_panel(bpy.types.Panel):
            bl_label = "Proof"
            bl_idname = "PROOF_PT_panel"
            bl_space_type = 'PROPERTIES'
            bl_region_type = 'WINDOW'
            bl_context = "scene"

            def draw(self, context):
                self.layout.operator(PROOF_OT_make.bl_idname)

        bpy.utils.register_class(PROOF_OT_make)
        bpy.utils.register_class(PROOF_PT_panel)

        check("operator reachable via bpy.ops",
              lambda: bpy.ops.proof.make.get_rna_type().name)
        check("panel registered as a type",
              lambda: hasattr(bpy.types, "PROOF_PT_panel"))
        check("IntProperty default survives registration",
              lambda: bpy.ops.proof.make.get_rna_type().properties["count"].default)

        before = len(bpy.data.objects)
        bpy.ops.proof.make(count=3)
        check("operator added exactly 3 objects",
              lambda: len(bpy.data.objects) - before)

        bpy.utils.unregister_class(PROOF_PT_panel)
        bpy.utils.unregister_class(PROOF_OT_make)
        check("unregister removed the panel type",
              lambda: not hasattr(bpy.types, "PROOF_PT_panel"))
        """
    )
    assert_checks(results)

    by_label = {r["label"]: r["detail"] for r in results}
    assert by_label["operator reachable via bpy.ops"] == "Make"
    assert by_label["IntProperty default survives registration"] == 2
    assert by_label["operator added exactly 3 objects"] == 3


def test_scene_can_be_written_and_rendered(tmp_path) -> None:
    results = run_in_blender(
        f"""
        import os
        bpy.ops.mesh.primitive_cube_add()
        scene = bpy.context.scene
        scene.render.engine = 'CYCLES'
        scene.cycles.device = 'CPU'
        scene.cycles.samples = 8
        scene.render.resolution_x = 32
        scene.render.resolution_y = 32
        scene.render.filepath = {str(tmp_path / "proof.png")!r}
        bpy.ops.render.render(write_still=True)
        check("render produced a file",
              lambda: os.path.getsize({str(tmp_path / "proof.png")!r}))
        bpy.ops.wm.save_as_mainfile(filepath={str(tmp_path / "proof.blend")!r})
        check("blend file written",
              lambda: os.path.getsize({str(tmp_path / "proof.blend")!r}))
        """,
        timeout=600,
    )
    assert_checks(results)
    for r in results:
        assert r["detail"] > 0, f"{r['label']} produced an empty file"
