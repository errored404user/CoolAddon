# CoolAddon

A Blender add-on, developed and tested against a real Blender interpreter.

## Development setup

The add-on is verified against Blender's own Python module (`bpy`) rather than a
mock, so operator registration, property definitions, RNA types, data-block
manipulation and even Cycles rendering are exercised for real.

```sh
./tools/setup_bpy_env.sh
```

That creates a venv, installs `bpy` (the genuine CPython build of Blender),
installs `pytest`, and builds the shim described below. It needs roughly 2 GB of
disk and a working `gcc`. Everything is installed outside the repository
(`~/.venv`, `~/.bpyshim`), so no binaries are committed.

## Running the tests

```sh
~/.venv/bin/python -m pytest tests -q
```

Set `BPY_PYTHON` to point at a different interpreter if your venv lives
elsewhere.

## Why there is a "shim"

`bpy` ships its own copies of almost all of Blender's dependencies, but it still
has `DT_NEEDED` entries on system X11/GL libraries that a slim container does not
have:

```
libGL.so.1  libGLX.so.0  libOpenGL.so.0  libICE.so.6  libSM.so.6
libXfixes.so.3  libXi.so.6  libXrender.so.1  libXt.so.6  libxkbcommon.so.0
```

Headless work never touches that windowing code, yet the dynamic linker refuses
to load the module until the libraries exist and export the referenced symbols.
`tools/build_bpy_shim.py` therefore creates empty stub shared objects with the
right SONAMEs and preloads one shim exporting exactly the 48 symbols the loader
reports as missing, discovered iteratively. They are all input/keyboard/OpenGL
context entry points:

```
XCloseDevice XFixesHideCursor XFixesShowCursor XFreeDeviceList XFreeDeviceState
XGetExtensionVersion XListInputDevices XOpenDevice XQueryDeviceState
XSelectExtensionEvent _XiGetDevicePresenceNotifyEvent glFinish glXChooseFBConfig
glXCreateContext glXCreateNewContext glXCreateWindow glXDestroyContext
glXGetCurrentContext glXGetCurrentDisplay glXGetCurrentDrawable glXGetProcAddress
glXGetProcAddressARB glXGetVisualFromFBConfig glXMakeContextCurrent
glXMakeCurrent glXQueryContext glXSwapBuffers xkb_*  (21 keyboard symbols)
```

### What this can and cannot verify

Reliable in this environment:

* `register()` / `unregister()`, class registration order, RNA type creation
* operators, panels, menus, property groups, `bpy.props` definitions and defaults
* `bpy.ops` invocation, mesh/data-block manipulation, modifiers, materials
* node trees, drivers, keyframes, collections
* saving and reloading `.blend` files, importers/exporters
* Cycles CPU rendering to an image file

**Not** verifiable here, because it needs a real window and GPU context:

* `draw()` callbacks and anything drawn in the 3D viewport, editors or overlays
* `gpu` module shader drawing, gizmos, `draw_handler_add`
* modal operators' interaction with the event loop, keymaps in practice
* modal timers, `bpy.app.timers` firing, workspace/UI state

If a stubbed symbol is ever genuinely called, it returns garbage and the process
will crash — so a failure in those areas must be reproduced in a desktop Blender
before it is trusted. Treat a crash near `gl*`, `X*` or `xkb_*` as
"retest locally", not as a real bug.

## Repository layout

```
tools/setup_bpy_env.sh     one-time environment setup
tools/build_bpy_shim.py    builds the stub libs + symbol shim (idempotent)
tests/blender_runner.py    runs checks inside a real Blender subprocess
tests/test_blender_harness.py   positive end-to-end checks
tests/test_harness_negative.py  negative controls proving the suite can fail
```
