# Claude Code guidance

## No unrequested side effects

Do not cause an effect outside the working tree unless the user asked for that
specific action in this session. Authorization is per action and does not carry
forward: approving a fix is not approval to execute it, and approving one run is
not approval for the next.

Ask first before any of these:

- triggering, re-running, or cancelling a GitHub Actions workflow
  (`gh workflow run`, `gh run rerun`, `gh run cancel`);
- changing repository, organization, or branch-protection settings
  (`gh api -X PUT/PATCH/POST` against a settings endpoint);
- creating, editing, merging, closing, or commenting on a pull request or issue;
- pushing to a shared branch, force-pushing, or deleting a remote branch;
- publishing a package, or calling any paid or rate-limited API.

Reading is always fine: `gh run view`, `gh run list`, `gh pr view`, `gh api` GET,
and any local command that only inspects state.

**Verification is not an exemption.** If the only way to confirm a change works
is one of the actions above, propose it — state what it would do, what it would
create, and what it would cost — then wait. Reporting a change as unverified is
better than a side effect the user did not expect. When such an action has
already been proposed and declined or left unanswered, do not perform it as a
"quick check" later in the same session.

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
