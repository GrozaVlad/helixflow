from pathlib import Path

from workers.msa.scheduling import a3m_depth


def test_a3m_depth_uses_deepest_alignment(tmp_path: Path):
    shallow = tmp_path / "a.a3m"
    deep = tmp_path / "b.a3m"
    shallow.write_text(">query\nAAAA\n", encoding="utf-8")
    deep.write_text(">query\nAAAA\n>hit1\nAAAA\n>hit2\nAAAA\n", encoding="utf-8")
    assert a3m_depth([shallow, deep]) == 3


def test_a3m_depth_ignores_other_files(tmp_path: Path):
    text = tmp_path / "notes.txt"
    text.write_text(">not-an-alignment\n", encoding="utf-8")
    assert a3m_depth([text]) == 0
