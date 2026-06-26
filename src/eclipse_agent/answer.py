"""Direct question answering for Eclipse via the configured LLM provider.

This is separate from the planner: the planner turns instructions into action
plans, while this turns a question into a concise spoken answer.
"""

from __future__ import annotations

from dataclasses import dataclass

from eclipse_agent.planner import LLMPlannerConfig, build_planner_config_from_env

ANSWER_SYSTEM_PROMPT = (
    "You are Eclipse, a concise voice assistant. Answer the user's question "
    "directly in one to three sentences, in the same language as the question. "
    "Your answer is spoken aloud, so do not use markdown, lists, or code blocks. "
    "If you do not know or it needs real-time data you lack, say so briefly."
)


@dataclass(frozen=True)
class AnswerResult:
    """Result of answering a question."""

    success: bool
    question: str
    answer: str
    message: str


class QuestionAnswerer:
    """Answer questions through an OpenAI-compatible chat completion."""

    def __init__(
        self,
        config: LLMPlannerConfig | None = None,
        *,
        client: object | None = None,
        system_prompt: str = ANSWER_SYSTEM_PROMPT,
    ) -> None:
        self.config = config or LLMPlannerConfig()
        self._client = client
        self.system_prompt = system_prompt

    @property
    def client(self) -> object:
        if self._client is None:
            try:
                from openai import OpenAI
            except ModuleNotFoundError as exc:
                raise RuntimeError(
                    "The official 'openai' package is required to answer questions."
                ) from exc
            self._client = OpenAI(
                api_key=self.config.api_key,
                base_url=self.config.base_url,
                timeout=self.config.timeout_seconds,
            )
        return self._client

    def answer(self, question: str) -> AnswerResult:
        normalized = " ".join(question.strip().split())
        if not normalized:
            return AnswerResult(False, normalized, "", "No question was provided.")
        try:
            completion = self.client.chat.completions.create(  # type: ignore[attr-defined]
                model=self.config.model,
                messages=[
                    {"role": "system", "content": self.system_prompt},
                    {"role": "user", "content": normalized},
                ],
                temperature=0.3,
                max_tokens=300,
            )
            text = _completion_text(completion)
        except Exception as exc:  # noqa: BLE001
            return AnswerResult(False, normalized, "", f"I could not answer that right now: {exc}")
        if not text:
            return AnswerResult(False, normalized, "", "The model returned an empty answer.")
        return AnswerResult(True, normalized, text, text)


def answer_question_from_env(question: str, *, provider: str | None = None) -> AnswerResult:
    """Answer a question using the LLM provider configured via env/.env."""

    config = build_planner_config_from_env(endpoint_url=None, model=None, provider=provider)
    return QuestionAnswerer(config).answer(question)


def render_answer_result(result: AnswerResult) -> str:
    """Render an answer result for CLI display."""

    if not result.success:
        return f"Answer [failed]: {result.message}"
    return f"Answer: {result.answer}"


def _completion_text(completion: object) -> str:
    choices = getattr(completion, "choices", None)
    if not choices:
        return ""
    message = getattr(choices[0], "message", None)
    content = getattr(message, "content", None)
    return content.strip() if isinstance(content, str) else ""
