from eclipse_agent import main as main_module
from eclipse_agent.answer import AnswerResult, QuestionAnswerer, render_answer_result
from eclipse_agent.planner import LLMPlannerConfig


class _FakeMessage:
    def __init__(self, content: str) -> None:
        self.content = content


class _FakeChoice:
    def __init__(self, content: str) -> None:
        self.message = _FakeMessage(content)


class _FakeCompletion:
    def __init__(self, content: str) -> None:
        self.choices = [_FakeChoice(content)]


class _FakeCompletions:
    def __init__(self, content: str) -> None:
        self.content = content
        self.calls: list[dict] = []

    def create(self, **kwargs):
        self.calls.append(kwargs)
        return _FakeCompletion(self.content)


class FakeAnswerClient:
    def __init__(self, content: str) -> None:
        self.chat = type("Chat", (), {"completions": _FakeCompletions(content)})()


def test_answer_returns_model_text():
    answerer = QuestionAnswerer(LLMPlannerConfig(), client=FakeAnswerClient("La fotosíntesis es un proceso."))

    result = answerer.answer("qué es la fotosíntesis")

    assert result.success is True
    assert result.answer == "La fotosíntesis es un proceso."


def test_answer_rejects_empty_question():
    answerer = QuestionAnswerer(LLMPlannerConfig(), client=FakeAnswerClient("x"))

    result = answerer.answer("   ")

    assert result.success is False


def test_answer_empty_model_response_fails():
    answerer = QuestionAnswerer(LLMPlannerConfig(), client=FakeAnswerClient(""))

    result = answerer.answer("qué es X")

    assert result.success is False


def test_answer_handles_client_error():
    class BoomCompletions:
        def create(self, **kwargs):
            raise RuntimeError("no network")

    class BoomClient:
        chat = type("Chat", (), {"completions": BoomCompletions()})()

    answerer = QuestionAnswerer(LLMPlannerConfig(), client=BoomClient())

    result = answerer.answer("qué es X")

    assert result.success is False
    assert "could not answer" in result.message.lower()


def test_render_answer_result():
    assert "Answer: hola" in render_answer_result(AnswerResult(True, "q", "hola", "hola"))


def test_cli_ask(monkeypatch, capsys):
    monkeypatch.setattr(
        main_module,
        "answer_question_from_env",
        lambda question, provider=None: AnswerResult(True, question, "42", "42"),
    )

    code = main_module.main(["ask", "--question", "cuánto es 6 por 7"])

    assert code == 0
    assert "Answer: 42" in capsys.readouterr().out
