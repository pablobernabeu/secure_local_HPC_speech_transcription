#!/usr/bin/env python3
"""
Compare a control decode of one FLEURS split with the multilingual arms.

The fourth arm of ``output/evaluation/fleurs_multilingual_summary.json``
decoded every language on cards none of the first three arms used, and its
raw scores differ from the third arm's on a few utterances per language.
The summary puts that down to the card as the only known difference, while
saying that no pair of arms on one model of card isolates it (audit finding
NEW-05). The control decodes one split again at the fourth arm's code on the
card the third arm used for it, so that only the card and the node holding
it separate the control from the fourth arm, and the code alone separates it
from the third. ``docs/next_control.md`` sets out the run and the rule this
module applies: the card explains the drift for that split if the control's
records match the third arm's exactly.

The summaries keep no transcripts. A decode is compared through what each
utterance's record keeps: its word alignment counts (hits, substitutions,
deletions, insertions, reference and hypothesis words) and its word, match
and character error rates. Two decodes that wrote the same words give the
same record; the same record does not prove the same words, so a match is
evidence of identical transcripts and not proof of it.

Inputs
------
``--control``
    The control's raw summary (``wer_summary_fleurs_<config>_<slug>.json``).
``--arm NAME=PATH``
    An arm's raw summary of the same split, repeatable. Each file's SHA-256
    must be the one ``--multilingual`` records for that arm, so the
    comparison is with the inputs the committed summary was built from.
``--target NAME``
    The arm the control is meant to reproduce.
``--preflight PATH``
    Optionally, the control's short pre-flight decode, compared with the
    first utterances of the control and of the target.
``--environment LABEL=PATH``
    The environment record a job wrote (``hpc/common/arc_common.sh``):
    ``control``, ``preflight`` or an arm's name. Read for the job, node,
    commit, card and modules, and its package list compared with the
    control's.
``--multilingual``
    The committed multilingual summary, for the recorded digests and each
    arm's code and card.

Records are paired by position, which is the order the split streams in.
Since a22a864 the benchmark renames a repeated utterance id with a
``__<n>`` suffix, which the first three arms' summaries do not carry, so ids
are compared without it; the streamed order and the reference word counts
must then agree, or the inputs are refused.

Output
------
A JSON record: the control's job, card, decode and run metadata; per arm,
the utterances compared and those whose record differs, field by field;
whether the target differs from each other arm on the same utterances as
the control does; the fields of the decode and run metadata in which the
control and an arm that records them differ; whether the jobs' package
lists agree; the outcome under the rule above; each input by file name and
digest, never by path; and this module's own run metadata.

The control behind the committed record, ``fleurs_es419_v100_control.json``,
is ARC jobs 9124739 (pre-flight) and 9124863 (the full split), whose
settings ``hpc/runs/fleurs_es419_v100.env`` records. Their outputs are under
``$DATA/speech_transcription_env/output/evaluation/controls/`` on ARC, the
arms' summaries where :mod:`evaluation.fleurs_multilingual` says, and the
fourth arm's environment records in ``audit2026/fleurs_ml/environment/``.

Usage::

    python -m evaluation.fleurs_control \\
        --control ctl/wer_summary_fleurs_es_419_whisper-large-v3.json \\
        --preflight pf/wer_summary_fleurs_es_419_whisper-large-v3.json \\
        --arm 1_before_fix=prefix_baseline/wer_summary_fleurs_es_419.json \\
        --arm 2_after_fix=afterfix_pregate/wer_summary_fleurs_es_419.json \\
        --arm 3_after_gate=wer_summary_fleurs_es_419.json \\
        --arm 4_after_audit=fleurs_ml/wer_summary_fleurs_es_419_whisper-large-v3.json \\
        --target 3_after_gate \\
        --environment control=ctl/environment/ctl_es419_v100_9124863_2.txt \\
        --environment preflight=pf/environment/pf_es419_v100_9124739_2.txt \\
        --environment 4_after_audit=fleurs_ml/environment/au_ml_8917984_2.txt \\
        --out output/evaluation/fleurs_es419_v100_control.json
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

_DEFAULT_MULTILINGUAL = Path("output/evaluation/fleurs_multilingual_summary.json")

#: What an utterance's record keeps, in the order the benchmark writes it.
RECORD_FIELDS = ("wer", "mer", "wil", "cer", "hits", "substitutions",
                 "deletions", "insertions", "reference_words",
                 "hypothesis_words")

#: The suffix the benchmark gives a repeated utterance id since a22a864.
_DUPLICATE_SUFFIX = re.compile(r"__\d+$")

#: The packages this module's run metadata records: it computes with the
#: standard library alone, so only the interpreter and the commit matter.
_PACKAGES = ()

#: Header keys of an environment record (hpc/common/arc_common.sh).
_ENV_KEYS = ("date", "host", "slurm_job_id", "slurm_array", "slurm_job_name",
             "slurm_cluster", "slurm_partition", "slurm_account", "git_commit",
             "git_modified_tracked_files")


def base_uid(name: str) -> str:
    """An utterance id without the ``__<n>`` suffix of a repeat."""
    return _DUPLICATE_SUFFIX.sub("", name)


def load_summary(path: Path) -> dict:
    """Read a raw benchmark summary, refusing anything else.

    Raises
    ------
    SystemExit
        If the file cannot be read, lacks ``benchmark``, ``summary`` or
        ``per_file``, or scores a condition other than ``raw``.
    """
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"cannot read {path}: {exc}") from exc
    if not isinstance(payload, dict) or not all(
            k in payload for k in ("benchmark", "summary", "per_file")):
        raise SystemExit(f"{path} is not a benchmark summary with per-file records")
    if payload["benchmark"].get("condition", "raw") != "raw":
        raise SystemExit(f"{path} scores {payload['benchmark']['condition']!r}, "
                         "not the raw hypothesis")
    return payload


def read_environment(path: Path) -> dict:
    """Read an environment record into its header, card, modules and packages.

    Returns ``{key: value}`` for the header keys of :data:`_ENV_KEYS`
    present, ``gpu`` (the first line under ``## GPU``), ``modules`` (the
    loaded modules, in order) and ``packages`` (the ``pip list
    --format=freeze`` lines, sorted).
    """
    lines = Path(path).read_text(encoding="utf-8").splitlines()
    out: dict = {}
    section = None
    modules: list[str] = []
    packages: list[str] = []
    for line in lines:
        if line.startswith("## "):
            section = line[3:].strip()
            continue
        if section is None:
            key, sep, value = line.partition(":")
            if sep and key.strip() in _ENV_KEYS:
                out[key.strip()] = value.strip()
        elif section == "GPU" and "gpu" not in out and line.strip():
            out["gpu"] = line.strip()
        elif section == "Loaded modules":
            modules += re.findall(r"\d+\)\s+(\S+)", line)
        elif section.startswith("pip list") and "==" in line:
            packages.append(line.strip())
    out["modules"] = modules
    out["packages"] = sorted(packages)
    return out


def compare_records(control: list, other: list) -> dict:
    """Compare two decodes' per-utterance records, paired by position.

    Returns the count compared and identical, and each differing utterance
    with the fields that differ and both values.

    Raises
    ------
    SystemExit
        If the decodes hold different numbers of utterances, or a pair
        differs in its id (without the repeat suffix) or its reference word
        count: the two did not score the same utterances in the same order.
    """
    if len(control) != len(other):
        raise SystemExit(f"the decodes hold {len(control)} and {len(other)} "
                         "utterances")
    differing = []
    for position, (a, b) in enumerate(zip(control, other, strict=True)):
        if base_uid(a["name"]) != base_uid(b["name"]):
            raise SystemExit(f"utterance {position}: {a['name']!r} against "
                             f"{b['name']!r}; the decodes streamed different orders")
        if a["reference_words"] != b["reference_words"]:
            raise SystemExit(f"utterance {a['name']!r}: {a['reference_words']} "
                             f"against {b['reference_words']} reference words")
        fields = {f: {"control": a.get(f), "other": b.get(f)}
                  for f in RECORD_FIELDS if a.get(f) != b.get(f)}
        if fields:
            differing.append({"uid": base_uid(a["name"]), "position": position,
                              "fields": fields})
    return {"utterances_compared": len(control),
            "identical": len(control) - len(differing),
            "differing": len(differing),
            "differing_utterances": differing}


def _flatten(block, prefix=""):
    if isinstance(block, dict):
        out = {}
        for key, value in block.items():
            out.update(_flatten(value, f"{prefix}{key}/"))
        return out
    return {prefix.rstrip("/"): block}


def provenance_differences(control: dict, other: dict) -> dict | None:
    """The decode and run-metadata fields in which two summaries differ.

    ``None`` when *other* records no ``run_metadata`` (the first three arms
    predate it). Compares ``benchmark`` (corpus, model, seed, revisions and
    the ``decode`` block: device, dtype, card, CUDA, cuDNN) and
    ``run_metadata`` (commit, tree state, Python, platform, packages).
    """
    if "run_metadata" not in other:
        return None
    a = _flatten({"benchmark": control["benchmark"],
                  "run_metadata": control.get("run_metadata") or {}})
    b = _flatten({"benchmark": other["benchmark"],
                  "run_metadata": other.get("run_metadata") or {}})
    return {key: {"control": a.get(key), "other": b.get(key)}
            for key in sorted(set(a) | set(b))
            if a.get(key) != b.get(key)}


def _digests(path: Path) -> dict:
    from provenance import sha256_file, sha256_text_file
    return {"file": Path(path).name, "sha256": sha256_file(path),
            "sha256_lf": sha256_text_file(path)}


def build(control_path: Path, arms: dict, target: str, multilingual: dict,
          preflight_path: Path | None = None, environments: dict | None = None,
          run_meta: dict | None = None) -> dict:
    """Compare the control with the arms and return the record.

    Parameters
    ----------
    control_path:
        The control's raw summary.
    arms:
        ``{arm name: raw summary path}``, the arm names those of
        ``multilingual["benchmark"]["arms"]``.
    target:
        The arm the control is meant to reproduce; one of *arms*.
    multilingual:
        The committed multilingual summary, parsed.
    preflight_path:
        The control's pre-flight summary, or ``None``.
    environments:
        ``{label: environment record path}``; ``control`` and an arm's name
        are compared on their package lists.
    run_meta:
        :func:`provenance.run_metadata`, read by the caller before writing.

    Raises
    ------
    SystemExit
        If *target* is not among *arms*, an arm is unknown to *multilingual*,
        an arm's digest is not the recorded one, a summary scores another
        split or model, or two decodes did not score the same utterances.
    """
    import hashlib

    environments = dict(environments or {})
    if target not in arms:
        raise SystemExit(f"--target {target!r} is not one of the arms {sorted(arms)}")
    recorded_arms = multilingual["benchmark"]["arms"]
    recorded = {(i["arm"], i["file"]): i["sha256"]
                for i in multilingual["benchmark"].get("inputs") or ()}
    control = load_summary(control_path)
    bench = control["benchmark"]
    config = bench.get("config")
    language = (multilingual.get("languages") or {}).get(config)
    if language is None:
        raise SystemExit(f"the multilingual summary has no {config!r} split")

    summaries = {}
    inputs = [{"role": "control", **_digests(control_path)}]
    for arm, path in arms.items():
        if arm not in recorded_arms:
            raise SystemExit(f"arm {arm!r} is not in the multilingual summary")
        digest = hashlib.sha256(Path(path).read_bytes()).hexdigest()
        if recorded.get((arm, Path(path).name)) != digest:
            raise SystemExit(f"{path}: SHA-256 {digest} is not the one the "
                             f"multilingual summary records for arm {arm}")
        payload = load_summary(path)
        for key in ("dataset", "config", "split", "model", "seed"):
            if payload["benchmark"].get(key) != bench.get(key):
                raise SystemExit(f"{path} records {key}={payload['benchmark'].get(key)!r}, "
                                 f"the control {bench.get(key)!r}")
        summaries[arm] = payload
        inputs.append({"role": "arm", "arm": arm, **_digests(path)})
    if len(control["per_file"]) != language["utterances"]:
        raise SystemExit(f"the control scored {len(control['per_file'])} utterances, "
                         f"the arms {language['utterances']}")

    comparisons = {}
    for arm, payload in summaries.items():
        result = compare_records(control["per_file"], payload["per_file"])
        comparisons[arm] = {
            "code": recorded_arms[arm].get("code"),
            "arc_jobs": recorded_arms[arm].get("arc_jobs"),
            "gpu": (recorded_arms[arm].get("gpus") or {}).get(config),
            "raw_macro_wer": payload["summary"]["macro_wer"],
            **{k: result[k] for k in ("utterances_compared", "identical", "differing")},
            "summary_identical": control["summary"] == payload["summary"],
            "differing_utterances": result["differing_utterances"],
            "provenance_differences": provenance_differences(control, payload),
        }
    # The control reproduces the target where their records agree; against
    # every other arm it should then differ exactly where the target does.
    target_records = summaries[target]["per_file"]
    for arm, payload in summaries.items():
        if arm == target:
            continue
        theirs = compare_records(target_records, payload["per_file"])
        ours = {d["uid"] for d in comparisons[arm]["differing_utterances"]}
        comparisons[arm]["target_differs_on_the_same_utterances"] = (
            {d["uid"] for d in theirs["differing_utterances"]} == ours)

    preflight = None
    if preflight_path is not None:
        pf = load_summary(preflight_path)
        n = len(pf["per_file"])
        inputs.append({"role": "preflight", **_digests(preflight_path)})
        preflight = {
            "utterances": n,
            "gpu": (pf["benchmark"].get("decode") or {}).get("gpu"),
            "git_commit": (pf.get("run_metadata") or {}).get("git_commit"),
            "matches_the_control": compare_records(
                pf["per_file"], control["per_file"][:n])["differing"] == 0,
            "matches_the_target": compare_records(
                pf["per_file"], target_records[:n])["differing"] == 0,
        }

    jobs, packages = {}, {}
    for label, path in sorted(environments.items()):
        env = read_environment(path)
        inputs.append({"role": "environment", "label": label, **_digests(path)})
        jobs[label] = {k: env.get(k) for k in (*_ENV_KEYS, "gpu")}
        jobs[label]["modules"] = env["modules"]
        jobs[label]["n_packages"] = len(env["packages"])
        packages[label] = env["packages"]
    # The package lists themselves stay out of the record, which says only
    # whether each job imported what the control did, version for version.
    if "control" in packages:
        for label in jobs:
            if label != "control":
                jobs[label]["packages_identical_to_control"] = (
                    packages[label] == packages["control"])

    target_cmp = comparisons[target]
    reproduces = (target_cmp["differing"] == 0 and target_cmp["summary_identical"])
    others = [a for a in comparisons if a != target]
    if reproduces:
        outcome = (
            f"The control reproduces arm {target}'s raw records of {config} on "
            f"all {target_cmp['utterances_compared']} utterances, and differs "
            "from each other arm on the utterances where that arm also "
            "departs from it. Where an arm records its decode and run "
            "metadata, the fields in which it differs from the control are "
            "listed under provenance_differences. The summaries keep no "
            "transcripts, so the records agree in their alignment counts and "
            "error rates, which the same words would give but do not prove.")
    else:
        outcome = (
            f"The control's raw records of {config} differ from arm {target}'s "
            f"on {target_cmp['differing']} utterance(s), so this control leaves "
            "the attribution of the drift unresolved.")
    result = {
        "description": (
            "A control decode of one FLEURS split at the fourth multilingual "
            "arm's code, on a card of the family the target arm decoded it on, "
            "compared record by record with the arms' raw summaries "
            "(evaluation.fleurs_control; audit finding NEW-05; "
            "docs/next_control.md)."),
        "config": config,
        "language": bench.get("language"),
        "model": bench.get("model"),
        "seed": bench.get("seed"),
        "target": target,
        "control": {
            "utterances": len(control["per_file"]),
            "n_renamed_duplicate_uids": bench.get("n_renamed_duplicate_uids"),
            "revisions": bench.get("revisions"),
            "decode": bench.get("decode"),
            "summary": control["summary"],
            "run_metadata": control.get("run_metadata"),
        },
        "comparisons": comparisons,
        "preflight": preflight,
        "jobs": jobs,
        "finding": {
            "reproduces_target": reproduces,
            "differs_from_others_where_target_does": all(
                comparisons[a]["target_differs_on_the_same_utterances"] for a in others),
            "transcripts_compared": False,
            "outcome": outcome,
        },
        "inputs": inputs,
    }
    if run_meta is None:
        from provenance import run_metadata
        run_meta = run_metadata(packages=_PACKAGES)
    result["run_metadata"] = run_meta
    return result


def _labelled(values, option: str) -> dict:
    out: dict[str, Path] = {}
    for value in values or ():
        label, sep, path = value.partition("=")
        if not sep or not label or not path:
            raise SystemExit(f"{option} takes LABEL=PATH, not {value!r}")
        if label in out:
            raise SystemExit(f"{option} names {label!r} twice")
        out[label] = Path(path)
    return out


def main(argv=None) -> int:
    """Run the command-line interface.

    Returns ``0`` and writes ``--out``; raises ``SystemExit`` with a message
    on a missing, mislabelled or mismatched input.
    """
    p = argparse.ArgumentParser(
        prog="evaluation.fleurs_control",
        description="Compare a control decode of a FLEURS split with the "
                    "multilingual arms, record by record.")
    p.add_argument("--control", type=Path, required=True)
    p.add_argument("--arm", action="append", required=True, metavar="NAME=PATH")
    p.add_argument("--target", required=True)
    p.add_argument("--preflight", type=Path, default=None)
    p.add_argument("--environment", action="append", metavar="LABEL=PATH")
    p.add_argument("--multilingual", type=Path, default=_DEFAULT_MULTILINGUAL)
    p.add_argument("--out", type=Path, required=True)
    args = p.parse_args(argv)

    from provenance import run_metadata
    # Read before the record is written, leaving it out of the dirty check.
    run_meta = run_metadata(packages=_PACKAGES, ignore=(args.out,))
    multilingual = json.loads(args.multilingual.read_text(encoding="utf-8"))
    result = build(args.control, _labelled(args.arm, "--arm"), args.target,
                   multilingual, args.preflight,
                   _labelled(args.environment, "--environment"), run_meta)
    result["inputs"].append({"role": "multilingual_summary",
                             **_digests(args.multilingual)})
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with open(args.out, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(json.dumps(result, indent=2, ensure_ascii=False) + "\n")
    for arm, cmp in result["comparisons"].items():
        print(f"  {arm:<15} {cmp['gpu']!s:<24} identical {cmp['identical']}"
              f"/{cmp['utterances_compared']}, differing {cmp['differing']}")
    print(f"  reproduces {args.target}: {result['finding']['reproduces_target']}")
    print(f"  written: {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
