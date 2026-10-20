"""The PreToolUse hook that refuses the commands which would deploy production."""

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
HOOK = ROOT / ".claude" / "hooks" / "block_commands.py"
SETTINGS = ROOT / ".claude" / "settings.json"
CLAUDE_CODE_BLOCKS_THE_TOOL_CALL = 2


def _run_hook(command: str) -> subprocess.CompletedProcess[str]:
    payload = {
        "hook_event_name": "PreToolUse",
        "tool_name": "Bash",
        "tool_input": {"command": command},
    }
    return subprocess.run(
        [sys.executable, str(HOOK)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.mark.parametrize(
    ("command", "says"),
    [
        ("gh release create v0.1.0 --generate-notes", "production deploy"),
        ("gh release edit v0.1.0 --draft=false", "production deploy"),
        ("GH_TOKEN=x gh release create v0.1.0", "production deploy"),
        ("env GH_TOKEN=x gh release create v0.1.0", "production deploy"),
        ("(gh release create v0.1.0)", "production deploy"),
        ('bash -c "gh release create v0.1.0"', "production deploy"),
        ("echo `gh release create v0.1.0`", "production deploy"),
        ("/usr/bin/gh release create v0.1.0", "production deploy"),
        ("cat <<'EOF'\nok\nEOF\ngit push --tags", "v* tag"),
        ("git -C /home/user/francisco-system push origin v0.1.0", "v* tag"),
        ("git -c push.followTags=true push --follow-tags", "v* tag"),
        ("git push origin +v0.1.0", "v* tag"),
        ("git tag v0.1.0 && git push origin v0.1.0", "v* tag"),
        ("git tag v0.1.0\ngit push origin v0.1.0", "v* tag"),
        ("git push --tags", "v* tag"),
        ("git push origin refs/tags/v0.1.0", "v* tag"),
        ("git push origin tag v0.1.0", "v* tag"),
    ],
)
def test_a_forbidden_command_is_refused_with_what_to_run_instead(command: str, says: str) -> None:
    result = _run_hook(command)

    assert result.returncode == CLAUDE_CODE_BLOCKS_THE_TOOL_CALL
    assert says in result.stderr


@pytest.mark.parametrize(
    "command",
    [
        "git push -u origin chore/claude-hooks-rules",
        "git -C /home/user/francisco-system push -u origin main",
        "gh release view v0.1.0",
        "gh release list --limit 5",
        "git tag --list 'v*'",
        "uv run pytest tests/test_command_hooks.py",
        "python -c 'print(\"git push --tags\")'",
        "git commit -F - <<'EOF'\nfeat: el hook bloquea (gh release create)\nEOF",
        "gh pr create --body-file - <<'EOF'\nAntes (git push --tags) pasaba.\nEOF",
        "git --no-pager log --oneline -3",
    ],
)
def test_an_allowed_command_runs(command: str) -> None:
    result = _run_hook(command)

    assert (result.returncode, result.stderr) == (0, "")


def test_the_hook_is_registered_for_every_bash_call() -> None:
    pre_tool_use = json.loads(SETTINGS.read_text())["hooks"]["PreToolUse"]

    commands = [
        hook["command"]
        for entry in pre_tool_use
        if entry["matcher"] == "Bash"
        for hook in entry["hooks"]
    ]
    assert any(command.endswith("/.claude/hooks/block_commands.py") for command in commands)
