
import pandas as pd

from src import logger


def test_prune_runs_keeps_newest_and_ignores_unrelated(tmp_path, monkeypatch):
    monkeypatch.setattr(logger, "LOG_DIR", tmp_path)
    monkeypatch.setattr(logger, "RUNS_INDEX", tmp_path / "runs.csv")
    ids = ["20240101-000000-000", "20240201-000000-000", "20240301-000000-000"]
    for run_id in ids:
        (tmp_path / run_id).mkdir()
    (tmp_path / "do-not-delete").mkdir()
    pd.DataFrame({"run_id": ids}).to_csv(logger.RUNS_INDEX, index=False)
    removed = logger.prune_runs(max_runs=2)
    assert removed == [ids[0]]
    assert (tmp_path / "do-not-delete").exists()
    assert logger.load_runs_index()["run_id"].astype(str).tolist() == ids[1:]
