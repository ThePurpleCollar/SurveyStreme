Review the most recent code changes for quality:

1. Run `git diff --name-only` to see changed files.
2. For each changed file, review against these criteria:
   - **CLAUDE.md rules**: coding conventions, import order, type hints
   - **No business logic in pages/**: UI code should call services/
   - **No hardcoded secrets**: API keys, URLs should come from .env
   - **Error handling**: LLM calls should have try/except
   - **Session state consistency**: SurveyDocument used correctly
3. Check for common issues:
   - Duplicate logic that already exists elsewhere
   - Missing type hints on function signatures
   - Functions longer than 50 lines (suggest splitting)
4. Report findings as actionable items.
