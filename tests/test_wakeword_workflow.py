import importlib.util
import sys
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "generate_wakeword.py"
SPEC = importlib.util.spec_from_file_location("generate_wakeword", SCRIPT_PATH)
assert SPEC and SPEC.loader
generate_wakeword = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = generate_wakeword
SPEC.loader.exec_module(generate_wakeword)


def test_wakeword_workflow_documents_samples_and_artifacts():
    guide = generate_wakeword.build_workflow_guide()

    assert "positive wakeword examples" in guide
    assert "negative/background examples" in guide
    assert "models/eclipse.onnx" in guide
    assert ".wakeword-training/eclipse" in guide


def test_evaluate_wakeword_scores_passes_with_strong_positive_and_low_false_activation():
    result = generate_wakeword.evaluate_wakeword_scores(
        positive_scores=(0.82, 0.91, 0.77),
        negative_scores=(0.01, 0.03, 0.04),
        positive_threshold=0.5,
        minimum_positive_detection_rate=0.8,
        maximum_false_activation_rate=0.1,
    )

    assert result.acceptable is True
    assert result.positive_detection_rate == 1.0
    assert result.false_activation_rate == 0.0
    assert "acceptable" in result.message
    assert "ECLIPSE_WAKEWORD_MODEL_PATH" in result.recommended_configuration


def test_evaluate_wakeword_scores_fails_without_promoting_weak_custom_model():
    result = generate_wakeword.evaluate_wakeword_scores(
        positive_scores=(0.12, 0.27, 0.19),
        negative_scores=(0.01, 0.03, 0.04),
        positive_threshold=0.5,
        minimum_positive_detection_rate=0.8,
        maximum_false_activation_rate=0.1,
    )

    assert result.acceptable is False
    assert result.positive_detection_rate == 0.0
    assert result.recommended_configuration == ""
    assert "keep builtin hey_jarvis" in result.message


def test_evaluate_wakeword_scores_fails_when_false_activations_are_too_high():
    result = generate_wakeword.evaluate_wakeword_scores(
        positive_scores=(0.82, 0.91, 0.77),
        negative_scores=(0.8, 0.03, 0.75),
        positive_threshold=0.5,
        minimum_positive_detection_rate=0.8,
        maximum_false_activation_rate=0.1,
    )

    assert result.acceptable is False
    assert result.false_activation_rate > 0.1
    assert result.recommended_configuration == ""
    assert "keep builtin hey_jarvis" in result.message
