#!/usr/bin/env python3
"""Generate the custom openwakeword model used by Eclipse.

The official openwakeword custom-model pipeline trains a phrase detector from
synthetic Piper samples, augmented audio, and precomputed negative feature
datasets. This script creates an Eclipse-specific training config and delegates
the heavy work to ``python -m openwakeword.train`` so the final artifact is the
runtime model expected by ``OpenWakeWordTrigger``:

    models/eclipse.onnx

Training is intentionally explicit because it requires large local assets:

* a clone of the openwakeword-compatible piper-sample-generator repository,
* background audio clips,
* room impulse response clips,
* a false-positive validation ``.npy`` feature file,
* at least one precomputed negative-feature ``.npy`` file.

Use ``--dry-run`` first to write the generated config and review the exact
training command without starting the GPU/CPU-heavy training job.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

DEFAULT_PHRASE = "eclipse"
DEFAULT_MODEL_NAME = "eclipse"
PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_WORK_DIR = PROJECT_ROOT / ".wakeword-training" / DEFAULT_MODEL_NAME
DEFAULT_OUTPUT_MODEL = PROJECT_ROOT / "models" / f"{DEFAULT_MODEL_NAME}.onnx"
DEFAULT_PIPER_SAMPLE_GENERATOR_PATH = PROJECT_ROOT / "piper-sample-generator"
DEFAULT_BACKGROUND_PATH = DEFAULT_WORK_DIR / "background_clips"
DEFAULT_RIR_PATH = DEFAULT_WORK_DIR / "mit_rirs"
DEFAULT_FALSE_POSITIVE_VALIDATION_DATA = DEFAULT_WORK_DIR / "validation_set_features.npy"
DEFAULT_FEATURE_DATA_FILE = (
    "ACAV100M_sample="
    f"{DEFAULT_WORK_DIR / 'openwakeword_features_ACAV100M_2000_hrs_16bit.npy'}"
)

REQUIRED_TRAINING_MODULES = (
    "openwakeword",
    "torch",
    "torchinfo",
    "torchmetrics",
    "scipy",
    "yaml",
    "tqdm",
)


@dataclass(frozen=True)
class TrainingCommand:
    """Generated openwakeword training command and config path."""

    command: tuple[str, ...]
    config_path: Path
    generated_model_path: Path
    output_model_path: Path


def main(argv: Sequence[str] | None = None) -> int:
    """Run the Eclipse wake-word generation workflow."""

    args = build_parser().parse_args(argv)
    try:
        command = prepare_training_command(args)
        print(f"Training config written to: {command.config_path}")
        print(f"Generated model will be copied to: {command.output_model_path}")
        print(f"Training command: {shlex_join(command.command)}")
        if args.dry_run:
            print("Dry run complete. No training command was executed.")
            return 0

        validate_training_environment(args)
        completed = subprocess.run(command.command, check=False)  # noqa: S603
        if completed.returncode != 0:
            print(
                f"openwakeword training failed with exit code {completed.returncode}.",
                file=sys.stderr,
            )
            return completed.returncode
        if args.skip_train_model:
            print("Model training was skipped. No ONNX model was copied.")
            return 0
        if not command.generated_model_path.exists():
            print(
                "openwakeword training completed but did not produce the expected "
                f"model: {command.generated_model_path}",
                file=sys.stderr,
            )
            return 1
        command.output_model_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(command.generated_model_path, command.output_model_path)
        print(f"Eclipse wake-word model ready: {command.output_model_path}")
        return 0
    except ValueError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        return 2
    except RuntimeError as exc:
        print(f"Environment error: {exc}", file=sys.stderr)
        return 3


def build_parser() -> argparse.ArgumentParser:
    """Build the command-line parser."""

    parser = argparse.ArgumentParser(
        description="Generate the custom openwakeword ONNX model for the Eclipse phrase.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--phrase", default=DEFAULT_PHRASE, help="Wake phrase to train.")
    parser.add_argument("--model-name", default=DEFAULT_MODEL_NAME, help="Output model stem.")
    parser.add_argument(
        "--work-dir",
        type=Path,
        default=DEFAULT_WORK_DIR,
        help="Directory for generated clips, features, config, and training output.",
    )
    parser.add_argument(
        "--output-model",
        type=Path,
        default=DEFAULT_OUTPUT_MODEL,
        help="Final ONNX model path consumed by Eclipse.",
    )
    parser.add_argument(
        "--piper-sample-generator-path",
        type=Path,
        default=DEFAULT_PIPER_SAMPLE_GENERATOR_PATH,
        help="Path containing generate_samples.py from the Piper sample generator.",
    )
    parser.add_argument(
        "--background-path",
        action="append",
        type=Path,
        default=[],
        help="Directory of background audio clips. Can be repeated.",
    )
    parser.add_argument(
        "--rir-path",
        action="append",
        type=Path,
        default=[],
        help="Directory of room impulse response clips. Can be repeated.",
    )
    parser.add_argument(
        "--false-positive-validation-data",
        type=Path,
        default=DEFAULT_FALSE_POSITIVE_VALIDATION_DATA,
        help="Precomputed false-positive validation .npy feature file.",
    )
    parser.add_argument(
        "--feature-data-file",
        action="append",
        default=[],
        metavar="NAME=PATH",
        help="Precomputed negative-feature .npy file. Can be repeated.",
    )
    parser.add_argument("--n-samples", type=int, default=10000, help="Synthetic train samples.")
    parser.add_argument(
        "--n-samples-val",
        type=int,
        default=2000,
        help="Synthetic validation samples.",
    )
    parser.add_argument("--steps", type=int, default=50000, help="Maximum training steps.")
    parser.add_argument("--tts-batch-size", type=int, default=50, help="Piper TTS batch size.")
    parser.add_argument(
        "--augmentation-batch-size",
        type=int,
        default=16,
        help="Audio augmentation batch size.",
    )
    parser.add_argument(
        "--augmentation-rounds",
        type=int,
        default=1,
        help="Number of augmentation passes over generated clips.",
    )
    parser.add_argument("--layer-size", type=int, default=32, help="DNN layer size.")
    parser.add_argument(
        "--max-negative-weight",
        type=int,
        default=1500,
        help="Maximum negative-class weight during auto training.",
    )
    parser.add_argument(
        "--target-false-positives-per-hour",
        type=float,
        default=0.2,
        help="Auto-training false-positive target.",
    )
    parser.add_argument(
        "--skip-generate-clips",
        action="store_true",
        help="Do not generate synthetic positive and adversarial clips.",
    )
    parser.add_argument(
        "--skip-augment-clips",
        action="store_true",
        help="Do not augment generated clips or compute features.",
    )
    parser.add_argument(
        "--skip-train-model",
        action="store_true",
        help="Do not train or export the ONNX model.",
    )
    parser.add_argument(
        "--overwrite-features",
        action="store_true",
        help="Recompute existing augmented openwakeword features.",
    )
    parser.add_argument(
        "--convert-to-tflite",
        action="store_true",
        help="Also request TFLite conversion after ONNX export.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Write config and print command without validating assets or training.",
    )
    return parser


def prepare_training_command(args: argparse.Namespace) -> TrainingCommand:
    """Write the generated config and return the openwakeword training command."""

    phrase = normalize_phrase(args.phrase)
    work_dir = args.work_dir.expanduser().resolve()
    output_model = args.output_model.expanduser().resolve()
    config_path = work_dir / f"{args.model_name}.training.yml"
    output_dir = work_dir / "output"
    generated_model_path = output_dir / f"{args.model_name}.onnx"

    config = build_training_config(
        phrase=phrase,
        model_name=args.model_name,
        work_dir=work_dir,
        output_dir=output_dir,
        piper_sample_generator_path=args.piper_sample_generator_path.expanduser().resolve(),
        background_paths=tuple(args.background_path) or (DEFAULT_BACKGROUND_PATH,),
        rir_paths=tuple(args.rir_path) or (DEFAULT_RIR_PATH,),
        false_positive_validation_data=args.false_positive_validation_data.expanduser().resolve(),
        feature_data_files=parse_feature_data_files(
            args.feature_data_file or [DEFAULT_FEATURE_DATA_FILE]
        ),
        n_samples=args.n_samples,
        n_samples_val=args.n_samples_val,
        steps=args.steps,
        tts_batch_size=args.tts_batch_size,
        augmentation_batch_size=args.augmentation_batch_size,
        augmentation_rounds=args.augmentation_rounds,
        layer_size=args.layer_size,
        max_negative_weight=args.max_negative_weight,
        target_false_positives_per_hour=args.target_false_positives_per_hour,
    )
    work_dir.mkdir(parents=True, exist_ok=True)
    config_path.write_text(json.dumps(config, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    command = [sys.executable, "-m", "openwakeword.train", "--training_config", str(config_path)]
    if not args.skip_generate_clips:
        command.append("--generate_clips")
    if not args.skip_augment_clips:
        command.append("--augment_clips")
    if args.overwrite_features:
        command.append("--overwrite")
    if not args.skip_train_model:
        command.append("--train_model")
    if args.convert_to_tflite:
        command.append("--convert_to_tflite")

    return TrainingCommand(
        command=tuple(command),
        config_path=config_path,
        generated_model_path=generated_model_path,
        output_model_path=output_model,
    )


def build_training_config(
    *,
    phrase: str,
    model_name: str,
    work_dir: Path,
    output_dir: Path,
    piper_sample_generator_path: Path,
    background_paths: tuple[Path, ...],
    rir_paths: tuple[Path, ...],
    false_positive_validation_data: Path,
    feature_data_files: dict[str, Path],
    n_samples: int,
    n_samples_val: int,
    steps: int,
    tts_batch_size: int,
    augmentation_batch_size: int,
    augmentation_rounds: int,
    layer_size: int,
    max_negative_weight: int,
    target_false_positives_per_hour: float,
) -> dict[str, object]:
    """Build an openwakeword training configuration for the Eclipse phrase."""

    if n_samples <= 0 or n_samples_val <= 0 or steps <= 0:
        raise ValueError("Sample counts and training steps must be positive.")
    if tts_batch_size <= 0 or augmentation_batch_size <= 0 or augmentation_rounds <= 0:
        raise ValueError("Batch sizes and augmentation rounds must be positive.")
    if layer_size <= 0 or max_negative_weight <= 0:
        raise ValueError("Layer size and maximum negative weight must be positive.")

    return {
        "model_name": model_name,
        "target_phrase": [phrase],
        "custom_negative_phrases": [],
        "n_samples": n_samples,
        "n_samples_val": n_samples_val,
        "tts_batch_size": tts_batch_size,
        "augmentation_batch_size": augmentation_batch_size,
        "piper_sample_generator_path": str(piper_sample_generator_path),
        "output_dir": str(output_dir),
        "rir_paths": [str(path.expanduser().resolve()) for path in rir_paths],
        "background_paths": [str(path.expanduser().resolve()) for path in background_paths],
        "background_paths_duplication_rate": [1 for _ in background_paths],
        "false_positive_validation_data_path": str(false_positive_validation_data),
        "augmentation_rounds": augmentation_rounds,
        "feature_data_files": {
            name: str(path.expanduser().resolve()) for name, path in feature_data_files.items()
        },
        "batch_n_per_class": {
            **{name: 1024 for name in feature_data_files},
            "adversarial_negative": 50,
            "positive": 50,
        },
        "model_type": "dnn",
        "layer_size": layer_size,
        "steps": steps,
        "max_negative_weight": max_negative_weight,
        "target_false_positives_per_hour": target_false_positives_per_hour,
        "working_directory": str(work_dir),
    }


def validate_training_environment(args: argparse.Namespace) -> None:
    """Validate dependencies and local training assets before running training."""

    missing_modules = [
        module for module in REQUIRED_TRAINING_MODULES if importlib.util.find_spec(module) is None
    ]
    if missing_modules:
        raise RuntimeError(
            "Missing training modules: "
            f"{', '.join(missing_modules)}. Install the wake-word training extra first."
        )

    piper_path = args.piper_sample_generator_path.expanduser().resolve()
    if not (piper_path / "generate_samples.py").exists():
        raise RuntimeError(
            "Piper sample generator is missing. Expected generate_samples.py under "
            f"{piper_path}. Clone an openwakeword-compatible piper-sample-generator there "
            "or pass --piper-sample-generator-path."
        )

    background_paths = tuple(args.background_path) or (DEFAULT_BACKGROUND_PATH,)
    rir_paths = tuple(args.rir_path) or (DEFAULT_RIR_PATH,)
    for path in (*background_paths, *rir_paths):
        resolved = path.expanduser().resolve()
        if not resolved.is_dir():
            raise RuntimeError(f"Required audio asset directory does not exist: {resolved}")

    false_positive_path = args.false_positive_validation_data.expanduser().resolve()
    if not false_positive_path.is_file():
        raise RuntimeError(
            "False-positive validation features are missing: "
            f"{false_positive_path}. Download or generate the openwakeword validation .npy file."
        )

    feature_data_files = parse_feature_data_files(
        args.feature_data_file or [DEFAULT_FEATURE_DATA_FILE]
    )
    for name, path in feature_data_files.items():
        resolved = path.expanduser().resolve()
        if not resolved.is_file():
            raise RuntimeError(
                f"Feature data file for {name!r} is missing: {resolved}. "
                "Provide precomputed openwakeword negative-feature data with --feature-data-file."
            )


def parse_feature_data_files(values: Sequence[str]) -> dict[str, Path]:
    """Parse NAME=PATH feature data file arguments."""

    parsed: dict[str, Path] = {}
    for value in values:
        if "=" not in value:
            raise ValueError(f"Feature data file must use NAME=PATH format: {value}")
        name, path = value.split("=", 1)
        name = name.strip()
        if not name:
            raise ValueError("Feature data file names cannot be empty.")
        parsed[name] = Path(path).expanduser()
    return parsed


def normalize_phrase(value: str) -> str:
    """Normalize and validate the target wake phrase."""

    phrase = " ".join(value.casefold().strip().split())
    if not phrase:
        raise ValueError("Wake phrase cannot be empty.")
    return phrase


def shlex_join(command: Sequence[str]) -> str:
    """Render a shell-safe command string for operator review."""

    import shlex

    return shlex.join(str(part) for part in command)


if __name__ == "__main__":
    raise SystemExit(main())
