from app.config import REPO_ROOT


async def test_shareable_output_and_exit_status(monkeypatch, capsys, nvidia_server, tmp_path):
    monkeypatch.syspath_prepend(str(REPO_ROOT))
    import check_nvidia

    monkeypatch.setattr(check_nvidia, "ROOT", tmp_path)

    key = "local-key-for-cli-probe"
    monkeypatch.setenv("NVIDIA_API_KEY", key)
    script, hp = nvidia_server
    monkeypatch.setenv("NVIDIA_PROXIES", f"http://cli-user:cli-pass@{hp}")
    script.reply({"ok": True})
    assert await check_nvidia.run(False) == 0
    output = capsys.readouterr().out
    assert "Прокси 1/1" in output and '{"ok": true}' in output
    assert key not in output and hp not in output and "cli-pass" not in output

    script.reply(status=401, body={"error": key})
    assert await check_nvidia.run(True) == 1
    output = capsys.readouterr().out
    assert "Прямой HTTPS" in output and "HTTP 401" in output and key not in output
