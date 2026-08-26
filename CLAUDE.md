# Claude Code guidance

## Toolchain execution

For ad-hoc toolchain invocations — e.g. a `python3 -c "..."` one-liner to
parse or transform data (JSON from a `gh api` call, etc.) — run it inside a
Docker container rather than invoking the host's local interpreter directly:

```sh
docker run --rm -v <file>:/data/<file>:ro python:3-slim python3 -c "..."
```

This also applies whenever a needed local tool or toolchain isn't available
on the host at all: use Docker as the fallback rather than asking to install
something locally. Skip Docker only when it's unavailable, or the task
specifically requires host-native execution (editing files outside a
mountable path, or needing host services Docker can't reach).
