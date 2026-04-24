# Tool Notes

## IMPORTANT: Actually Call Tools
You have real MCP tools available. When you need to create a file, you MUST call `edit_file` — do not generate fake output. The tool returns a SUCCESS or Error message. If you did not receive that message, the file was NOT created.

## Maintenance Proposals
To write a proposal, call: `edit_file(file_path="proposals/YYYY-MM-DD_title.md", content="...")`

Use this format for the content:

```markdown
# Proposal: [Short Title]
**Date**: YYYY-MM-DD
**Priority**: HIGH / MEDIUM / LOW
**Files affected**: list of files

## Problem
What's wrong and why it matters.

## Proposed Changes
### File: `path/to/file.py`
```diff
- old line
+ new line
```

## Risk Assessment
What could go wrong. Rollback plan.

## Verification
How to confirm the fix works.
```

Save proposals to: `proposals/YYYY-MM-DD_short-title.md`
