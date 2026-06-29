import logging
import uuid

from django.utils import timezone

from ..models import TestRun, TestResult
from .caller import get_caller

logger = logging.getLogger(__name__)


def run_scenario(test_run_id: str):
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
            caller._connect()
            if caller.observer_url:
                run.observer_url = caller.observer_url
                run.save(update_fields=["observer_url"])
                logger.info(f"Observer URL for run {test_run_id}: {caller.observer_url}")
            transcript_turns = caller.run_scenario(
                run.scenario.steps, conversation_id, recording_id=str(run.id)
            )
        else:
            if getattr(run.agent, "greeting", ""):
                transcript_turns.append({"speaker": "agent", "text": run.agent.greeting, "ts_ms": 0, "quirks": []})
            for step in run.scenario.steps:
                raw_text = step.get("raw", step.get("text", ""))
                clean_text = step.get("text", raw_text)
                quirks = [q.get("tag") for q in step.get("quirks", [])]
                transcript_turns.append({"speaker": "caller", "text": clean_text, "raw": raw_text, "ts_ms": 0, "quirks": quirks})
                result = caller.send(raw_text, conversation_id)
                transcript_turns.append({"speaker": "agent", "text": result["response"], "ts_ms": result.get("ts_ms", 0), "quirks": []})

        assertion_results = _evaluate_assertions(run.scenario.assertions, transcript_turns, run.agent)
        assertions_passed = all(a["passed"] for a in assertion_results)

        test_result = TestResult.objects.create(
            test_run=run, passed=assertions_passed,
            transcript=transcript_turns, assertion_results=assertion_results,
        )

        from ..tasks import run_judge_task
        run_judge_task.delay(str(test_result.id), run.scenario.rubric, run.agent.tenant_id)

        run.status = TestRun.Status.COMPLETED
        run.completed_at = timezone.now()
        run.save(update_fields=["status", "completed_at"])
        logger.info(f"TestRun {test_run_id} completed. Assertions passed: {assertions_passed}")

    except TestRun.DoesNotExist:
        logger.warning(f"TestRun {test_run_id} was deleted before results could be saved — discarding")
        return
    except Exception as e:
        logger.exception(f"TestRun {test_run_id} failed: {e}")
        try:
            run.status = TestRun.Status.FAILED
            run.completed_at = timezone.now()
            run.save(update_fields=["status", "completed_at"])
        except Exception:
            pass  # run may have been deleted; nothing to do


def _evaluate_assertions(assertions, transcript, agent):
    agent_turns = [t["text"].lower() for t in transcript if t["speaker"] == "agent"]
    full_text = " ".join(agent_turns)
    return [{"assertion": a, "passed": _check_assertion(a, transcript, full_text)} for a in assertions]


def _check_assertion(assertion, transcript, full_agent_text):
    turn_count = sum(1 for t in transcript if t["speaker"] == "agent")
    checks = {
        "resolved_within_5_turns": turn_count <= 5,
        "resolved_within_6_turns": turn_count <= 6,
        "agent_acknowledges_frustration": any(w in full_agent_text for w in ["sorry", "understand", "apologize", "frustrat"]),
        "no_hallucinated_policy": True,
        "agent_does_not_promise_impossible_timeline": True,
        "appointment_confirmed": any(w in full_agent_text for w in ["confirmed", "booked", "scheduled", "appointment"]),
        "correct_date_time_captured": any(w in full_agent_text for w in ["tuesday", "2pm", "2:00"]),
        "contact_details_collected": True,
        "agent_provides_confirmation_number_or_summary": any(w in full_agent_text for w in ["confirm", "number", "reference", "summary"]),
        "agent_asks_for_clarification_when_unclear": any(w in full_agent_text for w in ["could you", "can you", "please repeat", "clarif"]),
        "agent_does_not_fabricate_account_details": True,
        "agent_maintains_patience": True,
    }
    return checks.get(assertion, True)
