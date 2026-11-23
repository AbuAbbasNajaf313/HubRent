from app.envfile import load_env_file


def test_reads_values_and_skips_comments(tmp_path):
    f = tmp_path / ".env"
    f.write_text('# Kommentar\nA=1\nB = "zwei"\n\nC=\nexport D=vier\nKAPUTT\n', encoding="utf-8")
    env: dict[str, str] = {}
    load_env_file(f, env)
    assert env == {"A": "1", "B": "zwei", "C": "", "D": "vier"}


def test_existing_environment_wins(tmp_path):
    f = tmp_path / ".env"
    f.write_text("A=aus-datei\n", encoding="utf-8")
    env = {"A": "aus-shell"}
    load_env_file(f, env)
    assert env["A"] == "aus-shell"


def test_missing_file_is_fine(tmp_path):
    env: dict[str, str] = {}
    assert load_env_file(tmp_path / "fehlt.env", env) is False
    assert env == {}
