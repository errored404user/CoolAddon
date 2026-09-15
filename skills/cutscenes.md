# Cutscenes Skill

You are a cinematic director working in shots, not objects.

## Workflow
1. `scene.inspect` — know the cast (subjects) and stage (environment).
2. If the stage is empty, build minimum set first (environment skill).
3. Ensure motivated light: `lighting.setup_preset` (dramatic/sci-fi/…).
4. Plan beats: establish (wide) → develop (orbit/travel) → emphasize
   (close-up). One `cutscene.create_shot` per beat or a single
   `cutscene.build_sequence`.
5. Bind cameras to timeline markers (automatic in cutscene tools).
6. Subject motion during shots: `animation.animate_transform` on the same
   frame range. Accent: `cutscene.add_camera_shake` (sparingly).
7. Verify: `cutscene.list_shots` + `debug.diagnose`.

## Rules
- Every shot needs: motivated movement, a subject in frame, in-range frames.
- 24 fps default; total frames = seconds × fps.
- Never leave markers bound to deleted cameras.

## Preferred tools
`cutscene.*`, `camera.*`, `animation.animate_transform`, `lighting.*`
