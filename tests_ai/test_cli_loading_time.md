# CLI Loading Time

## `src/pythinker_code/__init__.py` be empty

**Scope**

`src/pythinker_code/__init__.py`

**Requirements**

The `src/pythinker_code/__init__.py` file must be empty, containing no code or imports.

## No unnecessary import in `src/pythinker_code/cli.py`

**Scope**

`src/pythinker_code/cli.py`

**Requirements**

The `src/pythinker_code/cli.py` file must not import any modules from `pythinker_code` or `pythinker_core`, except for `pythinker_code.constant`, at the top level.

## As-needed imports in `src/pythinker_code/app.py`

**Scope**

`src/pythinker_code/app.py`

**Requirements**

The `src/pythinker_code/app.py` file must not import any modules prefixed with `pythinker_code.ui` at the top level; instead, UI-specific modules should be imported within functions as needed.

<examples>

```python
# top-level
from pythinker_code.ui.shell import ShellApp  # Incorrect: top-level import of UI module

# inside function
async def run_shell_app(...):
    from pythinker_code.ui.shell import ShellApp  # Correct: import as needed
    app = ShellApp(...)
    await app.run()
```

</examples>

## `--help` should run fast

**Scope**

No specific source file.

**Requirements**

The time taken to run `uv run pythinker --help` must be less than 150 milliseconds on average over 5 runs after a 3-run warm-up.
