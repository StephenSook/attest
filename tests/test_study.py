"""The real-channel transfer study tooling.

The study's scientific validity rests on three properties, each pinned
here: the manifest is deterministic and mirrors the harness persona joint
distribution semantics; the analysis applies the HARNESS-calibrated qhat
(never fit on study data) with exactly the served gate's abstention rule;
and provenance is stamped on the output.
"""

import json
from pathlib import Path

from eval import personas
from eval.study import PROVENANCE, analyze, generate_manifest


def test_manifest_is_deterministic_and_label_semantics_hold() -> None:
    a = generate_manifest(n=36, seed=123)
    b = generate_manifest(n=36, seed=123)
    assert a == b
    assert generate_manifest(n=36, seed=124) != a
    for call in a["calls"]:
        if call["persona"] in {"evasive", "wrong_number", "refuses"}:
            assert call["truth"] == "unknown"
        else:
            assert call["truth"] in {"yes", "no"}
        assert call["line"], "every call needs a scripted respondent line"
    personas_seen = {c["persona"] for c in a["calls"]}
    assert personas_seen <= set(personas.PERSONAS)


def test_analyze_applies_harness_qhat_with_served_gate(tmp_path: Path) -> None:
    # Synthetic payloads built from the persona generator stand in for the
    # collected real calls, purely to exercise the analysis path; the real
    # study data is committed scrubbed payloads.
    scenarios = personas.generate(12, seed=99)
    manifest = {
        "seed": 99,
        "n": len(scenarios),
        "provenance": PROVENANCE,
        "calls": [
            {
                "n": i + 1,
                "persona": s.persona,
                "truth": s.truth,
                "line": "synthetic",
                "status": "done",
                "calle_call_id": f"call_test_{i}",
            }
            for i, s in enumerate(scenarios)
        ],
    }
    calls_dir = tmp_path / "calls"
    calls_dir.mkdir()
    for i, s in enumerate(scenarios):
        payload = {
            "id": f"call_test_{i}",
            "status": "completed",
            "recipients": [{"attempts": [{"transcript_turns": s.transcript_turns}]}],
        }
        (calls_dir / f"call_{i + 1:02d}.json").write_text(json.dumps(payload))
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest))

    report = analyze(
        manifest_path=manifest_path, calls_dir=calls_dir, out_path=tmp_path / "out.json"
    )
    assert report["provenance"] == PROVENANCE
    assert report["n_collected"] == 12
    assert report["qhat_source"].startswith("harness-calibrated")
    assert 0.0 <= report["empirical_coverage"] <= 1.0
    lo, hi = report["coverage_wilson_95"]
    assert 0.0 <= lo <= report["empirical_coverage"] <= hi <= 1.0
    # The abstention rule must mirror the served gate: singleton set AND a
    # non-unknown answer means answered; everything else abstains.
    for row in report["rows"]:
        if not row["abstain"]:
            assert row["set_size"] == 1
            assert row["answer"] in {"yes", "no"}


def test_deviation_protocol_exclusions_and_delivered_labels(tmp_path: Path) -> None:
    """An excluded call never enters the analysis; a relabeled call is
    scored against its DELIVERED truth, not the pre-registered one."""
    scenarios = personas.generate(3, seed=7)
    manifest = {
        "seed": 7,
        "n": 3,
        "provenance": PROVENANCE,
        "deviation_protocol": "test protocol",
        "calls": [
            {
                "n": 1,
                "persona": scenarios[0].persona,
                "truth": scenarios[0].truth,
                "line": "x",
                "status": "done",
                "calle_call_id": "c1",
            },
            {
                "n": 2,
                "persona": "hedging",
                "truth": "yes",
                "line": "x",
                "status": "done",
                "calle_call_id": "c2",
                "included": False,
            },
            {
                "n": 3,
                "persona": scenarios[2].persona,
                "truth": "no",
                "line": "x",
                "status": "done",
                "calle_call_id": "c3",
                "persona_delivered": scenarios[2].persona,
                "truth_delivered": scenarios[2].truth,
                "included": True,
            },
        ],
    }
    calls_dir = tmp_path / "calls"
    calls_dir.mkdir()
    for i, s in enumerate(scenarios):
        payload = {
            "id": f"c{i + 1}",
            "status": "completed",
            "recipients": [{"attempts": [{"transcript_turns": s.transcript_turns}]}],
        }
        (calls_dir / f"call_{i + 1:02d}.json").write_text(json.dumps(payload))
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest))

    report = analyze(
        manifest_path=manifest_path, calls_dir=calls_dir, out_path=tmp_path / "out.json"
    )
    assert report["n_collected"] == 2
    assert report["n_excluded_by_protocol"] == 1
    assert report["deviation_protocol"] == "test protocol"
    row3 = next(r for r in report["rows"] if r["n"] == 3)
    assert row3["truth"] == scenarios[2].truth


def test_committed_real_channel_report_is_current(tmp_path: Path) -> None:
    """The committed report must match a fresh regeneration from the
    committed data. Exists because a test once overwrote the shared results
    file with fixture output and the stale numbers nearly shipped."""
    committed_path = Path(__file__).parent.parent / "eval" / "results" / "real_channel.json"
    if not committed_path.exists():
        return
    fresh = analyze(out_path=tmp_path / "fresh.json")
    committed = json.loads(committed_path.read_text())
    for key in (
        "n_collected",
        "empirical_coverage",
        "abstention_rate",
        "accuracy_when_answering",
        "worst_case_coverage_all_excluded_as_misses",
    ):
        assert committed[key] == fresh[key], f"stale committed real_channel.json: {key}"
