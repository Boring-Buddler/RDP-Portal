"""Regression guard for finding S1: no process may start from a partial path."""

import ast
import pathlib

import pytest

from shared.windows_tools import powershell, system32_tool

SOURCE_ROOTS = ("portal_app", "workstation_agent", "shared", "deployment")


def test_system32_tool_returns_an_absolute_path() -> None:
    resolved = pathlib.Path(system32_tool("whoami.exe"))
    assert resolved.is_absolute()
    assert resolved.is_file()
    assert resolved.parent.name.casefold() == "system32"


def test_powershell_resolves_to_the_windows_copy() -> None:
    resolved = pathlib.Path(powershell())
    assert resolved.is_absolute()
    assert resolved.is_file()
    assert "windowspowershell" in str(resolved).casefold()


@pytest.mark.parametrize(
    "name",
    [
        "",
        "whoami",  # missing suffix
        "..\\whoami.exe",
        "sub/dir/whoami.exe",
        "C:\\Windows\\System32\\whoami.exe",
        "whoami.exe ",
    ],
)
def test_system32_tool_rejects_anything_but_a_plain_executable_name(name: str) -> None:
    with pytest.raises(ValueError):
        system32_tool(name)


def test_missing_tool_raises_an_oserror_callers_already_handle() -> None:
    # Call sites wrap the lookup in `except (OSError, subprocess.SubprocessError)`,
    # so an absent tool must degrade there instead of escaping as a new type.
    with pytest.raises(OSError):
        system32_tool("definitely-not-a-windows-tool.exe")


def _string_literal_commands(path: pathlib.Path) -> list[tuple[int, str]]:
    """Return (line, name) for every subprocess call whose argv[0] is a literal."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    found: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        target = node.func
        name = getattr(target, "attr", None) or getattr(target, "id", None)
        if name not in {"run", "Popen", "call", "check_output", "check_call"}:
            continue
        if not node.args:
            continue
        argv = node.args[0]
        if not isinstance(argv, ast.List) or not argv.elts:
            continue
        first = argv.elts[0]
        if isinstance(first, ast.Constant) and isinstance(first.value, str):
            found.append((first.lineno, first.value))
    return found


def test_no_subprocess_call_starts_a_bare_executable_name() -> None:
    """argv[0] must never be a plain literal such as "whoami" or "schtasks.exe".

    Resolution belongs in shared.windows_tools (portal/agent) or the installer's
    own system32_tool, so CreateProcess cannot search the working directory.
    """
    root = pathlib.Path(__file__).resolve().parent.parent
    offenders: list[str] = []
    for source_root in SOURCE_ROOTS:
        for path in sorted((root / source_root).rglob("*.py")):
            for line, value in _string_literal_commands(path):
                # An absolute path is fine; a bare name or relative path is not.
                if not pathlib.PureWindowsPath(value).is_absolute():
                    offenders.append(f"{path.relative_to(root).as_posix()}:{line}: {value!r}")
    assert not offenders, "argv[0] must be resolved to an absolute path:\n" + "\n".join(offenders)
