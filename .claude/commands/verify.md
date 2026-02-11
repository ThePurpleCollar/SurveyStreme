Run the verification procedure for the most recently worked-on task:

1. Read `docs/roadmap.md` to find the most recent in-progress task.
2. Read the task file in `docs/tasks/` for that task.
3. Execute every item in the **Verification Checklist** section.
4. If a **Smoke Test Script** is provided, run it.
5. Run the global verification from CLAUDE.md:
   - `python -c "from app import *; print('import OK')"`
   - `python -m py_compile` on all modified files
   - `python -m pytest tests/ -v` if tests exist
6. Report results clearly:
   - ✅ for passed checks
   - ❌ for failed checks with error details
7. If all pass, ask if the task should be marked complete in `docs/roadmap.md`.
