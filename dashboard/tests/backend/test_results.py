import csv
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from backend.results import artifact_path, list_artifacts, read_series, read_trajectory, run_directory, read_calculation_checks


class ResultDataTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.run = SimpleNamespace(id="run-test", status="SUCCEEDED", result={}, output_root=str(self.root),
                                   plan=SimpleNamespace(normalized_inputs={"steps": 10}))
        self.directory = self.root / self.run.id
        (self.directory / "aimd").mkdir(parents=True)

    def positions(self, frames):
        path = self.directory / "aimd" / "positions.csv"
        with path.open("w", newline="") as stream:
            writer = csv.writer(stream)
            writer.writerow(["step", "time_fs"] + [f"{atom}_{axis}_A" for atom in ("O", "H1", "H2") for axis in "xyz"])
            for step, time_fs in frames:
                writer.writerow([step, time_fs, 0.1, 0.2, 0.3, 1.1, 1.2, 1.3, 2.1, 2.2, 2.3])
        return path

    def test_checks_use_saved_limits_and_mark_short_run_gate_inapplicable(self):
        (self.directory / "aimd" / "metrics.json").write_text(json.dumps({
            "simulation": {"total_energy_drift_eV": -0.02, "linear_total_energy_drift_eV_per_ps": 9.0},
            "acceptance": {"checks": {"total_energy_drift_within_limit": True, "linear_energy_drift_within_limit": True},
                           "metric_applicability": {"linear_energy_drift": {"applicable_as_hard_gate": False, "hard_gate_minimum_steps": 100}}}
        }), encoding="utf-8")
        (self.directory / "aimd" / "resolved_config.yaml").write_text("aimd:\n  max_total_energy_drift_eV: 0.03\n", encoding="utf-8")
        checks = read_calculation_checks(self.run)
        self.assertEqual(checks[0]["criterion"], "绝对值 ≤ 0.03 eV")
        self.assertEqual(checks[0]["observed"], "0.02 eV")
        self.assertIn("仅供参考", checks[1]["criterion"])
        self.assertIn("100", checks[1]["criterion"])

    def test_checks_do_not_invent_missing_historical_thresholds(self):
        (self.directory / "aimd" / "run_summary.json").write_text(json.dumps({
            "acceptance": {"checks": {"total_energy_drift_within_limit": False}},
            "simulation": {"total_energy_drift_eV": float("nan")}
        }), encoding="utf-8")
        checks = read_calculation_checks(self.run)
        self.assertFalse(checks[0]["passed"])
        self.assertIn("未保存阈值", checks[0]["criterion"])
        self.assertIsNone(checks[0]["observed"])
        json.dumps(checks, allow_nan=False)

    def test_missing_or_malformed_check_records_are_unavailable(self):
        self.assertEqual(read_calculation_checks(self.run), [])
        (self.directory / "aimd" / "metrics.json").write_text('{"acceptance": "invalid"}', encoding="utf-8")
        self.assertEqual(read_calculation_checks(self.run), [])

    def test_trajectory_preserves_actual_steps_times_and_atom_order(self):
        self.positions([(0, 0.0), (5, 0.75), (10, 1.5)])
        result = read_trajectory(self.run, start=1, limit=1)
        self.assertEqual(result["symbols"], ["O", "H", "H"])
        self.assertEqual(result["frames"], [{"step": 5, "time_fs": 0.75,
                                            "positions": [[0.1, 0.2, 0.3], [1.1, 1.2, 1.3], [2.1, 2.2, 2.3]]}])
        self.assertEqual(result["total"], 3)
        self.assertEqual(result["units"], {"positions": "Å", "time": "fs"})
        self.assertTrue(result["complete"])

    def test_trajectory_page_is_bounded_and_out_of_range_is_empty(self):
        self.positions([(index, index * 0.1) for index in range(601)])
        first = read_trajectory(self.run, limit=10000)
        second = read_trajectory(self.run, start=500, limit=500)
        self.assertEqual(first["limit"], 500)
        self.assertEqual(len(first["frames"]), 500)
        self.assertEqual(len(second["frames"]), 101)
        self.assertEqual(second["frames"][0]["step"], 500)
        self.assertEqual(read_trajectory(self.run, start=601)["frames"], [])
        for kwargs in ({"start": -1}, {"limit": 0}, {"start": 1.5}, {"limit": True}):
            with self.assertRaises(ValueError):
                read_trajectory(self.run, **kwargs)

    def test_trajectory_terminal_partial_data_and_truncated_row(self):
        path = self.positions([(0, 0.0), (5, 0.5)])
        with path.open("a") as stream:
            stream.write("6,0.6,0.1,0.2\n")
            stream.write("7,0.7,nan,0,0,0,0,0,0,0,0\n")
        for status in ("FAILED", "CANCELLED", "SUCCEEDED"):
            self.run.status = status
            result = read_trajectory(self.run)
            self.assertFalse(result["complete"])
            self.assertEqual(result["total"], 2)
            self.assertEqual(result["invalid_rows"], 2)
        self.run.status = "RUNNING"
        result = read_trajectory(self.run)
        self.assertEqual(result["frames"], [])
        self.assertEqual(result["reason"], "run_not_terminal")

    def test_missing_oxygen_is_not_invented_from_hydrogen_coordinates(self):
        (self.directory / "aimd" / "positions.csv").write_text(
            "step,time_fs,H1_x_A,H1_y_A,H1_z_A,H2_x_A,H2_y_A,H2_z_A\n0,0,0,0,1,1,0,0\n")
        result = read_trajectory(self.run)
        self.assertFalse(result["available"])
        self.assertEqual(result["reason"], "invalid_trajectory_columns")

    def test_series_uses_recorded_energy_and_omits_incomplete_rows(self):
        (self.directory / "aimd" / "md_log.csv").write_text(
            "step,time_fs,potential_energy_eV,kinetic_energy_eV,total_energy_eV,temperature_K,ood_nearest_training_distance\n"
            "0,0,-7.2,0.1,-7.1,300,nan\n10,1.25,-7.3,0.2,-7.1,310,0.2\n11,1.3,-7.4\n")
        self.run.status = "RUNNING"
        result = read_series(self.run)
        self.assertTrue(result["available"])
        self.assertEqual([row["step"] for row in result["items"]], [0, 10])
        self.assertEqual(result["items"][1]["time_fs"], 1.25)
        self.assertEqual(result["items"][0]["total_energy_eV"], -7.1)
        self.assertIsNone(result["items"][0]["ood_nearest_training_distance"])
        self.assertEqual(result["invalid_rows"], 1)
        json.dumps(result, allow_nan=False)

    def test_missing_outputs_do_not_turn_demo_summary_into_scientific_data(self):
        self.run.result = {"is_demo": True, "summary": {"energy_ev": -76.4312}}
        self.assertEqual(read_series(self.run)["items"], [])
        self.assertEqual(read_trajectory(self.run)["frames"], [])

    def test_artifact_allowlist_paths_missing_files_and_symlinks(self):
        (self.directory / "aimd" / "metrics.json").write_text('{"value":1}')
        (self.directory / "checkpoint.pt").write_bytes(b"model")
        (self.directory / "job.json").write_text('{"private":"config"}')
        (self.directory / "figures").mkdir()
        (self.directory / "figures" / "custom.png").write_bytes(b"PNG")
        outside = self.root / "outside.csv"
        outside.write_text("secret")
        (self.directory / "aimd" / "escaped.csv").symlink_to(outside)
        manifest = {"artifacts": [{"relative_path": name} for name in (
            "aimd/metrics.json", "figures/custom.png", "missing.csv", "checkpoint.pt", "job.json",
            "../outside.csv", "/etc/passwd", "aimd/escaped.csv", "..\\outside.csv",
        )]}
        (self.directory / "artifact_manifest.json").write_text(json.dumps(manifest))
        artifacts = {item["name"]: item for item in list_artifacts(self.run)}
        self.assertEqual(set(artifacts), {"aimd/metrics.json", "figures/custom.png", "missing.csv", "artifact_manifest.json"})
        self.assertFalse(artifacts["missing.csv"]["available"])
        self.assertNotIn("download_url", artifacts["missing.csv"])
        metric = artifacts["aimd/metrics.json"]
        self.assertEqual(artifact_path(self.run, metric["id"]).read_text(), '{"value":1}')
        self.assertIn(metric["id"], metric["download_url"])
        with self.assertRaises(FileNotFoundError):
            artifact_path(self.run, artifacts["missing.csv"]["id"])
        with self.assertRaises(ValueError):
            artifact_path(self.run, "../outside.csv")
        with self.assertRaises(FileNotFoundError):
            artifact_path(self.run, "artifact-" + "0" * 24)

    def test_symlink_swap_after_listing_is_rechecked(self):
        metrics = self.directory / "aimd" / "metrics.json"
        metrics.write_text("{}")
        item = next(item for item in list_artifacts(self.run) if item["name"] == "aimd/metrics.json")
        metrics.unlink()
        outside = self.root / "private.json"
        outside.write_text("private")
        metrics.symlink_to(outside)
        with self.assertRaises(FileNotFoundError):
            artifact_path(self.run, item["id"])

    def test_stored_location_wins_and_legacy_location_is_found(self):
        self.assertEqual(run_directory(self.run, self.root / "other"), self.directory)
        self.run.output_root = None
        fake_dashboard = self.root / "new-repo" / "dashboard"
        legacy = fake_dashboard.parent / "fusion-platform" / "ray-outputs" / self.run.id
        legacy.mkdir(parents=True)
        with patch("backend.results._DASHBOARD", fake_dashboard), patch.dict("os.environ", {}, clear=True):
            self.assertEqual(run_directory(self.run), legacy)

    def test_invalid_run_id_and_escaping_run_directory_are_rejected(self):
        self.run.id = "../elsewhere"
        with self.assertRaises(ValueError):
            run_directory(self.run)
        self.run.id = "run-link"
        with tempfile.TemporaryDirectory() as outside:
            (self.root / self.run.id).symlink_to(outside, target_is_directory=True)
            with self.assertRaises(ValueError):
                run_directory(self.run)


if __name__ == "__main__":
    unittest.main()
