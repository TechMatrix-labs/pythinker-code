Record a short working-memory note for THIS mission: a decision you made, evidence
you found, a blocker, or the next step. This is your private per-session scratchpad —
the *why* and *what-next* behind the user-visible todo list (which the `SetTodoList`
tool owns). Notes persist across compaction and help you (and future sessions) resume.

Use `kind` to classify: `decision` | `evidence` | `blocker` | `next` | `note`.
Keep each note tight (a few sentences). Do NOT store secrets. Wrap anything the user
asked to keep out of memory in `<private>...</private>` — it is stripped before storage.
