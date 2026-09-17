from pathlib import Path

from updater.runner import CommandRunner


def test_run_shell_captures_stdout_and_stderr_separately():
    runner = CommandRunner()

    result = runner.run_shell("echo out; echo err >&2")

    assert result.stdout == "out\n"
    assert result.stderr == "err\n"
    assert result.ok


def test_run_shell_captures_nonzero_exit_code():
    runner = CommandRunner()

    result = runner.run_shell("exit 3")

    assert result.returncode == 3
    assert not result.ok


def test_run_shell_streams_output_live_to_this_process_stdout_and_stderr(capsys):
    runner = CommandRunner()

    result = runner.run_shell("echo hello; echo world >&2")

    captured = capsys.readouterr()
    # the output must appear on this process' real stdout/stderr (streamed
    # to the job log), not just be returned on the CommandResult
    assert "hello" in captured.out
    assert "world" in captured.err
    assert result.stdout == "hello\n"
    assert result.stderr == "world\n"


def test_run_shell_runs_in_given_cwd(tmp_path):
    runner = CommandRunner()

    result = runner.run_shell("pwd", cwd=tmp_path)

    assert Path(result.stdout.strip()).resolve() == tmp_path.resolve()
