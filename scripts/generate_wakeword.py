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
import os
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
DEFAULT_PIPER_GENERATOR_MODEL = (
    DEFAULT_PIPER_SAMPLE_GENERATOR_PATH / "models" / "en-us-libritts-high.pt"
)
DEFAULT_BACKGROUND_PATH = DEFAULT_WORK_DIR / "background_clips"
DEFAULT_RIR_PATH = DEFAULT_WORK_DIR / "mit_rirs"
DEFAULT_FALSE_POSITIVE_VALIDATION_DATA = DEFAULT_WORK_DIR / "validation_set_features.npy"
DEFAULT_FEATURE_DATA_FILE = (
    "ACAV100M_sample="
    f"{DEFAULT_WORK_DIR / 'openwakeword_features_ACAV100M_2000_hrs_16bit.npy'}"
)
DEFAULT_CUSTOM_NEGATIVE_PHRASES = (
    "computer",
    "calendar",
    "message",
    "settings",
    "window",
    "music",
    "weather",
    "notebook",
    "system",
    "sunlight",
)

REQUIRED_TRAINING_MODULES = (
    "openwakeword",
    "torch",
    "torchinfo",
    "torchmetrics",
    "scipy",
    "yaml",
    "tqdm",
    "pronouncing",
    "audiomentations",
    "torch_audiomentations",
    "speechbrain",
    "torchaudio",
    "mutagen",
    "acoustics",
    "piper_sample_generator",
)


@dataclass(frozen=True)
class TrainingCommand:
    """Generated openwakeword training command and config path."""

    command: tuple[str, ...]
    config_path: Path
    generated_model_path: Path
    output_model_path: Path
    environment: dict[str, str]


@dataclass(frozen=True)
class WakewordEvaluationResult:
    """Evaluation gate result for a candidate custom wake-word model."""

    acceptable: bool
    positive_detection_rate: float
    false_activation_rate: float
    message: str
    recommended_configuration: str = ""


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
        completed = subprocess.run(command.command, check=False, env=command.environment)  # noqa: S603
        if completed.returncode != 0:
            if command.generated_model_path.exists():
                copy_model_artifacts(command.generated_model_path, command.output_model_path)
                print(
                    "openwakeword training returned a non-zero exit code after "
                    "exporting the ONNX model. The optional TFLite conversion can "
                    "fail when onnx-tf is not installed, but Eclipse only needs the "
                    f"ONNX artifact. Copied model to: {command.output_model_path}",
                    file=sys.stderr,
                )
                return 0
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
        copy_model_artifacts(command.generated_model_path, command.output_model_path)
        print(f"Eclipse wake-word model ready: {command.output_model_path}")
        return 0
    except ValueError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        return 2
    except RuntimeError as exc:
        print(f"Environment error: {exc}", file=sys.stderr)
        return 3


def build_workflow_guide() -> str:
    """Return the operator workflow for safe Eclipse wake-word customization."""

    return "\n".join(
        [
            "Eclipse wakeword customization workflow:",
            "1. Capture positive wakeword examples: record several clean clips saying 'eclipse'.",
            "2. Capture or provide negative/background examples: room noise, speech without the wakeword, and common near-miss phrases.",
            f"3. Train into the work directory: {DEFAULT_WORK_DIR.relative_to(PROJECT_ROOT)}.",
            f"4. Export the candidate model artifact: {DEFAULT_OUTPUT_MODEL.relative_to(PROJECT_ROOT)}.",
            "5. Evaluate positive detection and false activation rates before promotion.",
            "6. If evaluation fails, keep builtin hey_jarvis as the default fallback.",
        ]
    )


def evaluate_wakeword_scores(
    *,
    positive_scores: Sequence[float],
    negative_scores: Sequence[float],
    positive_threshold: float,
    minimum_positive_detection_rate: float,
    maximum_false_activation_rate: float,
    model_path: Path = DEFAULT_OUTPUT_MODEL,
) -> WakewordEvaluationResult:
    """Evaluate a custom wake-word model without requiring live audio in tests."""

    if not positive_scores:
        raise ValueError("At least one positive wakeword score is required.")
    if not negative_scores:
        raise ValueError("At least one negative/background score is required.")
    if not 0 <= positive_threshold <= 1:
        raise ValueError("Positive threshold must be between 0 and 1.")
    if not 0 <= minimum_positive_detection_rate <= 1:
        raise ValueError("Minimum positive detection rate must be between 0 and 1.")
    if not 0 <= maximum_false_activation_rate <= 1:
        raise ValueError("Maximum false activation rate must be between 0 and 1.")

    positive_detection_rate = _rate_at_or_above(positive_scores, positive_threshold)
    false_activation_rate = _rate_at_or_above(negative_scores, positive_threshold)
    acceptable = (
        positive_detection_rate >= minimum_positive_detection_rate
        and false_activation_rate <= maximum_false_activation_rate
    )
    if acceptable:
        return WakewordEvaluationResult(
            acceptable=True,
            positive_detection_rate=positive_detection_rate,
            false_activation_rate=false_activation_rate,
            message=(
                "Custom wake-word model is acceptable; use it with builtin "
                "hey_jarvis fallback still enabled."
            ),
            recommended_configuration=f"ECLIPSE_WAKEWORD_MODEL_PATH={model_path}",
        )
    return WakewordEvaluationResult(
        acceptable=False,
        positive_detection_rate=positive_detection_rate,
        false_activation_rate=false_activation_rate,
        message=(
            "Custom wake-word model did not pass evaluation; keep builtin hey_jarvis "
            "as the default and do not promote this model automatically."
        ),
    )


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
        help=(
            "Path containing generate_samples.py or the modern "
            "piper_sample_generator package checkout."
        ),
    )
    parser.add_argument(
        "--piper-generator-model",
        type=Path,
        default=DEFAULT_PIPER_GENERATOR_MODEL,
        help="Piper LibriTTS generator .pt model used by the compatibility shim.",
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
    parser.add_argument(
        "--custom-negative-phrase",
        action="append",
        default=[],
        help="Additional phrase to synthesize as an adversarial negative. Can be repeated.",
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
        piper_sample_generator_path=prepare_piper_sample_generator_path(args, work_dir),
        background_paths=tuple(args.background_path) or (DEFAULT_BACKGROUND_PATH,),
        rir_paths=tuple(args.rir_path) or (DEFAULT_RIR_PATH,),
        false_positive_validation_data=args.false_positive_validation_data.expanduser().resolve(),
        feature_data_files=parse_feature_data_files(
            args.feature_data_file or [DEFAULT_FEATURE_DATA_FILE]
        ),
        custom_negative_phrases=tuple(args.custom_negative_phrase)
        or DEFAULT_CUSTOM_NEGATIVE_PHRASES,
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
        environment=build_training_environment(work_dir),
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
    custom_negative_phrases: tuple[str, ...],
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
        "custom_negative_phrases": [normalize_phrase(phrase) for phrase in custom_negative_phrases],
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

    work_dir = args.work_dir.expanduser().resolve()
    piper_path = prepare_piper_sample_generator_path(args, work_dir)
    if not (piper_path / "generate_samples.py").exists():
        raise RuntimeError(
            "Piper sample generator is missing. Expected generate_samples.py under "
            f"{piper_path}. Clone an openwakeword-compatible piper-sample-generator there "
            "or pass --piper-sample-generator-path."
        )

    piper_generator_model = args.piper_generator_model.expanduser().resolve()
    if not piper_generator_model.is_file():
        raise RuntimeError(
            "Piper generator model is missing: "
            f"{piper_generator_model}. Download en_US-libritts_r-medium.pt from "
            "the piper-sample-generator release or pass --piper-generator-model."
        )
    if not Path(f"{piper_generator_model}.json").is_file():
        raise RuntimeError(
            "Piper generator model metadata is missing: "
            f"{piper_generator_model}.json. The piper-sample-generator checkout "
            "normally includes this JSON next to the model path."
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


def _rate_at_or_above(scores: Sequence[float], threshold: float) -> float:
    return sum(1 for score in scores if float(score) >= threshold) / len(scores)


def prepare_piper_sample_generator_path(args: argparse.Namespace, work_dir: Path) -> Path:
    """Return an openwakeword-compatible Piper sample generator path.

    openwakeword 0.6 imports ``generate_samples`` from a top-level
    ``generate_samples.py`` file. Modern ``piper-sample-generator`` exposes the
    same function from the ``piper_sample_generator`` package and requires the
    generator model path as an explicit argument. To keep Eclipse setup
    reproducible, this function creates a tiny compatibility shim in the
    training work directory when the cloned repository uses the modern package
    layout.
    """

    piper_path = args.piper_sample_generator_path.expanduser().resolve()
    if (piper_path / "generate_samples.py").exists():
        return piper_path

    if not (piper_path / "piper_sample_generator" / "__main__.py").exists():
        return piper_path

    shim_dir = work_dir / "piper_sample_generator_shim"
    shim_dir.mkdir(parents=True, exist_ok=True)
    generator_model = args.piper_generator_model.expanduser().resolve()
    shim_path = shim_dir / "generate_samples.py"
    shim_path.write_text(
        "\n".join(
            [
                '"""Compatibility shim for openwakeword synthetic sample generation."""',
                "",
                "from __future__ import annotations",
                "",
                "import sys",
                "from pathlib import Path",
                "",
                "import numpy as np",
                "import soundfile as sf",
                "from scipy.signal import resample_poly",
                "",
                f"sys.path.insert(0, {str(piper_path)!r})",
                "",
                "from piper_sample_generator.__main__ import generate_samples as _generate_samples",
                "",
                f'DEFAULT_MODEL = Path({str(generator_model)!r})',
                "",
                "def generate_samples(*args, **kwargs):",
                '    """Generate samples using the configured Piper generator model."""',
                "    kwargs.setdefault('model', DEFAULT_MODEL)",
                "    output_dir = Path(kwargs.get('output_dir', args[1] if len(args) > 1 else '.'))",
                "    result = _generate_samples(*args, **kwargs)",
                "    _resample_output_wavs(output_dir)",
                "    return result",
                "",
                "def _resample_output_wavs(output_dir: Path, target_sample_rate: int = 16000) -> None:",
                "    for wav_path in output_dir.glob('*.wav'):",
                "        audio, sample_rate = sf.read(wav_path, dtype='float32')",
                "        if sample_rate == target_sample_rate:",
                "            continue",
                "        if audio.ndim > 1:",
                "            audio = audio.mean(axis=1)",
                "        gcd = np.gcd(sample_rate, target_sample_rate)",
                "        resampled = resample_poly(audio, target_sample_rate // gcd, sample_rate // gcd)",
                "        sf.write(wav_path, resampled, target_sample_rate, subtype='PCM_16')",
                "",
            ]
        ),
        encoding="utf-8",
    )
    return shim_dir


def build_training_environment(work_dir: Path) -> dict[str, str]:
    """Build the environment used by the openwakeword training subprocess."""

    patch_dir = work_dir / "python_runtime_patches"
    patch_dir.mkdir(parents=True, exist_ok=True)
    (patch_dir / "sitecustomize.py").write_text(
        "\n".join(
            [
                '"""Runtime compatibility patches for Eclipse wake-word training."""',
                "",
                "from __future__ import annotations",
                "",
                "try:",
                "    import soundfile as sf",
                "    import torchaudio",
                "",
                "    if not hasattr(torchaudio, 'info'):",
                "        class _AudioInfo:",
                "            def __init__(self, info):",
                "                self.num_frames = int(info.frames)",
                "                self.sample_rate = int(info.samplerate)",
                "",
                "        def _info(path):",
                "            return _AudioInfo(sf.info(path))",
                "",
                "        torchaudio.info = _info",
                "except Exception:",
                "    pass",
                "",
            ]
        ),
        encoding="utf-8",
    )
    env = os.environ.copy()
    existing_pythonpath = env.get("PYTHONPATH")
    env["PYTHONPATH"] = (
        str(patch_dir)
        if not existing_pythonpath
        else f"{patch_dir}{os.pathsep}{existing_pythonpath}"
    )
    return env


def copy_model_artifacts(generated_model_path: Path, output_model_path: Path) -> None:
    """Copy the ONNX model and any external-data sidecar emitted by PyTorch."""

    output_model_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(generated_model_path, output_model_path)

    generated_sidecar = Path(f"{generated_model_path}.data")
    if generated_sidecar.exists():
        shutil.copy2(generated_sidecar, Path(f"{output_model_path}.data"))


def shlex_join(command: Sequence[str]) -> str:
    """Render a shell-safe command string for operator review."""

    import shlex

    return shlex.join(str(part) for part in command)


if __name__ == "__main__":
    raise SystemExit(main())
