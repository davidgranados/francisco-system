#!/usr/bin/env python3
"""PreToolUse hook: refuse Bash commands this repo forbids, with what to run instead."""

import json
import re
import shlex
import sys
from collections.abc import Callable
from dataclasses import dataclass

SEPARATOR_CHARACTERS = ";&|\n()`"
TAG_REF = re.compile(r"^\+?(refs/tags/|[^:]*:refs/tags/)?v\d")
ENVIRONMENT_ASSIGNMENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")
COMMAND_WRAPPERS = {"env", "sudo", "command", "exec", "nohup", "time"}
SHELLS = {"sh", "bash", "zsh"}
SHELL_FLAGS_WITH_A_SCRIPT = re.compile(r"^-[a-z]*c[a-z]*$")
HEREDOC = re.compile(r"<<-?\s*(['\"]?)([A-Za-z_][A-Za-z0-9_]*)\1")
GIT_OPTIONS_WITH_A_VALUE = {"-C", "-c", "--git-dir", "--work-tree", "--namespace"}
RELEASE_SUBCOMMANDS_THAT_PUBLISH = {"create", "edit"}


@dataclass(frozen=True)
class ForbiddenCommand:
    matches: Callable[[list[str]], bool]
    reason: str


def _is_release_publish(words: list[str]) -> bool:
    return words[:2] == ["gh", "release"] and bool(
        set(words[2:3]) & RELEASE_SUBCOMMANDS_THAT_PUBLISH
    )


def _is_tag_push(words: list[str]) -> bool:
    if words[:2] != ["git", "push"]:
        return False
    arguments = words[2:]
    return any(
        word in ("--tags", "--follow-tags") or TAG_REF.match(word) for word in arguments
    ) or any(
        arguments[index] == "tag" and TAG_REF.match(arguments[index + 1])
        for index in range(len(arguments) - 1)
    )


FORBIDDEN_COMMANDS = [
    ForbiddenCommand(
        _is_release_publish,
        "Publishing a GitHub release IS the production deploy (docs/despliegue.md). "
        "Open the PR and hand back; a person cuts the release.",
    ),
    ForbiddenCommand(
        _is_tag_push,
        "Pushing a v* tag feeds the production deploy (docs/despliegue.md). "
        "Push the branch only: git push -u origin <branch>.",
    ),
]


def _segments(command: str) -> list[list[str]]:
    lexer = shlex.shlex(command, posix=True, punctuation_chars=SEPARATOR_CHARACTERS)
    lexer.whitespace = " \t\r"
    lexer.whitespace_split = True
    try:
        tokens = list(lexer)
    except ValueError:
        tokens = command.split()
    segments: list[list[str]] = [[]]
    for token in tokens:
        if set(token) <= set(SEPARATOR_CHARACTERS):
            segments.append([])
        else:
            segments[-1].append(token)
    return [words for words in segments if words]


def _without_prefixes(words: list[str]) -> list[str]:
    """The command as the shell runs it: no ``VAR=value``, no wrapper, no git option."""
    index = 0
    while index < len(words) and (
        ENVIRONMENT_ASSIGNMENT.match(words[index]) or words[index] in COMMAND_WRAPPERS
    ):
        index += 1
    words = (
        [words[index].rsplit("/", maxsplit=1)[-1], *words[index + 1 :]]
        if index < len(words)
        else []
    )
    if words[:1] != ["git"]:
        return words
    index = 1
    while index < len(words) and words[index].startswith("-"):
        index += 2 if words[index] in GIT_OPTIONS_WITH_A_VALUE else 1
    return ["git", *words[index:]]


def _nested_scripts(words: list[str]) -> list[str]:
    """The scripts a ``sh -c "..."`` inside this command runs, which the shell parses again."""
    return [
        words[index + 2]
        for index in range(len(words) - 2)
        if words[index] in SHELLS and SHELL_FLAGS_WITH_A_SCRIPT.match(words[index + 1])
    ]


def _without_heredoc_bodies(command: str) -> str:
    """The command without the text a heredoc feeds it, which is data, not commands."""
    kept: list[str] = []
    delimiter: str | None = None
    for line in command.split("\n"):
        if delimiter is not None:
            if line.strip() == delimiter:
                delimiter = None
            continue
        kept.append(line)
        if (heredoc := HEREDOC.search(line)) is not None:
            delimiter = heredoc.group(2)
    return "\n".join(kept)


def refusal_for(command: str) -> str | None:
    for words in _segments(_without_heredoc_bodies(command)):
        command_words = _without_prefixes(words)
        for forbidden in FORBIDDEN_COMMANDS:
            if forbidden.matches(command_words):
                return forbidden.reason
        for script in _nested_scripts(command_words):
            refusal = refusal_for(script)
            if refusal is not None:
                return refusal
    return None


def main() -> int:
    payload = json.load(sys.stdin)
    refusal = refusal_for(payload.get("tool_input", {}).get("command", ""))
    if refusal is None:
        return 0
    sys.stderr.write(f"{refusal}\n")
    return 2


if __name__ == "__main__":
    sys.exit(main())
