"""Negative controls: the harness must actually be able to fail.

A green suite is worthless if it cannot go red, so these tests deliberately
break things inside Blender and assert the failure surfaces here rather than
being silently swallowed.
"""

from __future__ import annotations

import pytest

from blender_runner import BlenderError, assert_checks, run_in_blender

pytestmark = pytest.mark.blender


def test_exception_inside_an_operator_is_reported() -> None:
    results = run_in_blender(
        """
        class NEG_OT_boom(bpy.types.Operator):
            bl_idname = "neg.boom"
            bl_label = "Boom"

            def execute(self, context):
                raise ValueError("deliberate failure")

        bpy.utils.register_class(NEG_OT_boom)
        # invoke() surfaces the exception; calling through bpy.ops re-raises it
        try:
            bpy.ops.neg.boom()
        except Exception as exc:
            check("operator raised", lambda: f"{type(exc).__name__}: {exc}")
        else:
            check("operator raised", lambda: (_ for _ in ()).throw(
                AssertionError("expected the operator to raise")))
        bpy.utils.unregister_class(NEG_OT_boom)
        """
    )
    assert_checks(results)
    detail = results[0]["detail"]
    # bpy.ops does not re-raise the original exception: it wraps it in a
    # RuntimeError whose message embeds the Python traceback.
    assert detail.startswith("RuntimeError:"), detail
    assert "ValueError: deliberate failure" in detail


def test_wrong_assertion_fails_the_check() -> None:
    results = run_in_blender("check('bad math', lambda: 1 / 0)")
    assert results[0]["ok"] is False
    assert "ZeroDivisionError" in results[0]["detail"]
    with pytest.raises(AssertionError, match="bad math"):
        assert_checks(results)


def test_crash_in_child_does_not_hang_the_suite() -> None:
    # A hard process exit must surface as BlenderError, not stall pytest.
    with pytest.raises(BlenderError, match="no results"):
        run_in_blender("import os\nos._exit(3)\n", timeout=60)


def test_unknown_bpy_api_is_caught() -> None:
    # Guards against the classic 'this API was renamed between versions' bug.
    results = run_in_blender(
        "check('bogus attribute', lambda: bpy.types.Scene.this_does_not_exist)"
    )
    assert results[0]["ok"] is False
    assert "AttributeError" in results[0]["detail"]
