---
name: "Commit & Push Milestone"
description: "Commits and pushes code at major project milestones"
trigger: manual
---

# Commit & Push Milestone

When triggered, stage all changes, create a descriptive commit message summarizing the milestone achieved, and push to the remote repository.

## Steps

1. Run `git status --short` to see what has changed.
2. If there are no changes, inform the user that there's nothing to commit.
3. Review the changed files and generate a concise, meaningful commit message that describes the milestone (e.g., "Add SCADA telemetry tools", "Implement leak detection agent", "Configure AgentCore deployment").
4. Stage all changes: `git add -A`
5. Commit with the generated message: `git commit -m "<message>"`
6. Check if a remote is configured: `git remote -v`
7. If a remote exists, push: `git push`
8. If no remote exists, inform the user the commit was saved locally and they need to add a remote with `git remote add origin <url>` before pushing.
9. Summarize what was committed and the commit hash.
