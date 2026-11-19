import subprocess
from pathlib import Path

HOOKS = Path(__file__).parents[1] / ".githooks"


def git(repo, *args):
    return subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True).stdout


def test_hook_strips_claude_attribution(tmp_path):
    git(tmp_path, "init", "-q")
    git(tmp_path, "config", "user.name", "t")
    git(tmp_path, "config", "user.email", "t@example.com")
    git(tmp_path, "config", "core.hooksPath", str(HOOKS))
    (tmp_path / "f.txt").write_text("x")
    git(tmp_path, "add", "f.txt")
    msg = (
        "Add f\n\nBody line.\n\n"
        "Generated with [Claude Code](https://claude.com/claude-code)\n"
        "Co-Authored-By: Claude <noreply@anthropic.com>\n"
        "Co-authored-by: Friend <friend@example.com>\n"
    )
    git(tmp_path, "commit", "-q", "-m", msg)
    saved = git(tmp_path, "log", "-1", "--format=%B")
    assert "anthropic" not in saved.lower()
    assert "Claude Code" not in saved
    assert "Body line." in saved
    assert "Friend <friend@example.com>" in saved
