import uuid
import logging
from django.utils import timezone

from apps.agents.models import Call, Transcript
from .models import TestRun, TestResult, JudgeScore
from .caller import get_caller

logger = logging.getLogger(__name__)


def run_scenario(test_run_id: str):
    """
    Execute a single scenario against an agent.
    Works for both text and audio modes via CallerInterface.
    """
    try:
        run = TestRun.objects.select_related("agent", "scenario").get(id=test_run_id)
    except TestRun.DoesNotExist:
        logger.error(f"TestRun {test_run_id} not found")
        return

    run.status = TestRun.Status.RUNNING
    run.started_at = timezone.now()
    run.save(update_fields=["status", "started_at"])

    caller = get_caller(run.mode, run.agent)
    conversation_id = str(uuid.uuid4())
    transcript_turns = []

    try:
        if run.mode == TestRun.Mode.AUDIO and hasattr(caller, "run_scenario"):
            # Connect first so we can capture and store the observer URL before
            # the scenario starts — anyone with the URL can join while the call runs.
            caller._connect()
            if caller.observer_url:
                run.observer_url = caller.observer_url
                run.save(update_fields=["observer_url"])
                logger.info(f"Observer URL for run {test_run_id}: {caller.observer_url}")

            # Audio mode: hand off the full scenario to the Pipecat caller bot.
            # It handles TTS, Daily WebRTC, and ElevenLabs Scribe v2 STT end-to-end.
            transcript_turns = caller.run_scenario(
                run.scenario.steps, conversation_id, recording_id=str(run.id)
            )
        else:
            # Text mode: if agent has a greeting, surface it as the first turn
            # before the scenario steps begin (AgentChat history is already seeded).
            if getattr(run.agent, "greeting", ""):
                transcript_turns.append({
                    "speaker": "agent",
                    "text": run.agent.greeting,
                    "ts_ms": 0,
                    "quirks": [],
                })

            # Text mode: iterate steps one by one, injecting text directly.
            for step in run.scenario.steps:
                raw_text = step.get("raw", step.get("text", ""))
                clean_text = step.get("text", raw_text)
                quirks = [q.get("tag") for q in step.get("quirks", [])]

                caller_turn = {
                    "speaker": "caller",
                    "text": clean_text,
                    "raw": raw_text,
                    "ts_ms": 0,
                    "quirks": quirks,
                }
                transcript_turns.append(caller_turn)

                result = caller.send(raw_text, conversation_id)
                agent_turn = {
                    "speaker": "agent",
                    "text": result["response"],
                    "ts_ms": result.get("ts_ms", 0),
                    "quirks": [],
                }
                transcript_turns.append(agent_turn)

        # Evaluate assertions (simple heuristic checks, real ones from LLM judge)
        assertion_results = _evaluate_assertions(
            run.scenario.assertions, transcript_turns, run.agent
        )
        assertions_passed = all(a["passed"] for a in assertion_results)

        # Create TestResult
        test_result = TestResult.objects.create(
            test_run=run,
            passed=assertions_passed,
            transcript=transcript_turns,
            assertion_results=assertion_results,
        )

        # Trigger LLM judge async in same tenant schema
        from .tasks import run_judge_task
        from django.db import connection
        run_judge_task.delay(str(test_result.id), run.scenario.rubric, schema_name=connection.schema_name)

        run.status = TestRun.Status.COMPLETED
        run.completed_at = timezone.now()
        run.save(update_fields=["status", "completed_at"])

        logger.info(f"TestRun {test_run_id} completed. Assertions passed: {assertions_passed}")

    except Exception as e:
        logger.exception(f"TestRun {test_run_id} failed: {e}")
        run.status = TestRun.Status.FAILED
        run.completed_at = timezone.now()
        run.save(update_fields=["status", "completed_at"])


def _evaluate_assertions(assertions: list, transcript: list, agent) -> list:
    """
    Lightweight heuristic assertion evaluation.
    LLM judge handles semantic scoring separately.
    """
    agent_turns = [t["text"].lower() for t in transcript if t["speaker"] == "agent"]
    full_text = " ".join(agent_turns)

    results = []
    for assertion in assertions:
        passed = _check_assertion(assertion, transcript, full_text)
        results.append({"assertion": assertion, "passed": passed})
    return results


def _check_assertion(assertion: str, transcript: list, full_agent_text: str) -> bool:
    """Map assertion names to simple checks. Extend as needed."""
    turn_count = sum(1 for t in transcript if t["speaker"] == "agent")

    checks = {
        "resolved_within_5_turns": turn_count <= 5,
        "resolved_within_6_turns": turn_count <= 6,
        "agent_acknowledges_frustration": any(
            word in full_agent_text for word in ["sorry", "understand", "apologize", "frustrat"]
        ),
        "no_hallucinated_policy": True,  # semantic — deferred to LLM judge
        "agent_does_not_promise_impossible_timeline": True,  # semantic
        "appointment_confirmed": any(
            word in full_agent_text for word in ["confirmed", "booked", "scheduled", "appointment"]
        ),
        "correct_date_time_captured": any(
            word in full_agent_text for word in ["tuesday", "2pm", "2:00"]
        ),
        "contact_details_collected": True,  # semantic
        "agent_provides_confirmation_number_or_summary": any(
            word in full_agent_text for word in ["confirm", "number", "reference", "summary"]
        ),
        "agent_asks_for_clarification_when_unclear": any(
            word in full_agent_text for word in ["could you", "can you", "please repeat", "clarif"]
        ),
        "agent_does_not_fabricate_account_details": True,  # semantic
        "agent_maintains_patience": True,  # semantic
    }
    return checks.get(assertion, True)  # unknown assertions default to pass (judge handles them)
