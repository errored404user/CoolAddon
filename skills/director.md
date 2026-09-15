# Director Skill

You run the full production pipeline autonomously and coherently.

## Pipeline (in order — never skip ahead)
1. **Understand**: `scene.inspect`. Reuse assets; note gaps.
2. **Subject**: modeling skill (or character skill when a rig is needed).
3. **Stage**: environments skill (theme matches the subject).
4. **Look**: materials skill + lighting skill (one art direction).
5. **Motion**: animation skill (subject performance).
6. **Story**: cutscenes skill (shots on the SAME frame range).
7. **Verify**: `debug.diagnose`, then `optimization.analyze` if heavy.
8. **Report**: what was built, where (collections/names), frame range,
   cameras/shots, and what to tweak next.

## Rules
- One frame range, one camera story, one mood — coherence beats quantity.
- Dependencies are law: no animation before subjects, no shots before the set.
- If a step fails, recover (rename/retry) or route around it — never leave
  a half-broken scene silently. Say what needs manual help.
- Render a still (`rendering.render`) as the final proof when asked.

## Preferred tools
All domains, orchestrated through `agent.execute` plans or direct calls.
