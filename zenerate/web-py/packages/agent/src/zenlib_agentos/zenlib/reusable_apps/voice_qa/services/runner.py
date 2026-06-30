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
        # Both AudioCaller (Pipecat/Daily) and RemoteAudioCaller (ElevenLabs WS)
        # expose run_scenario; turn-by-turn TextCaller does not. Keying off the
        # capability lets remote ElevenLabs agents take the audio path even when
        # the run's mode is "text".
        if hasattr(caller, "run_scenario"):
            # Give the during-call judge sub-agent the scenario's rubric.
            if hasattr(caller, "rubric"):
                caller.rubric = run.scenario.rubric
            caller._connect()
            if caller.observer_url:
                run.observer_url = caller.observer_url
                run.save(update_fields=["observer_url"])
                logger.info(f"Observer URL for run {test_run_id}: {caller.observer_url}")
            transcript_turns = caller.run_scenario(
                run.scenario.steps, conversation_id, recording_id=str(run.id)
            )
            # Remote agent may have hung up mid-call — record why for the run page.
            reason = getattr(caller, "disconnect_reason", "")
            if reason:
                run.disconnect_reason = reason
                run.save(update_fields=["disconnect_reason"])
                logger.warning(f"TestRun {test_run_id} agent disconnected: {reason}")
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
        import httpx
        # Transient capacity/overload errors from pipecat — re-raise so the
        # Celery task can retry with backoff instead of permanently failing the run.
        if isinstance(e, httpx.HTTPStatusError) and e.response.status_code in (429, 502, 503):
            logger.warning(f"TestRun {test_run_id} got transient {e.response.status_code} from pipecat — will retry")
            try:
                run.status = TestRun.Status.QUEUED
                run.started_at = None
                run.save(update_fields=["status", "started_at"])
            except Exception:
                pass
            raise
        logger.exception(f"TestRun {test_run_id} failed: {e}")
        try:
            run.status = TestRun.Status.FAILED
            run.completed_at = timezone.now()
            run.error_message = str(e)
            run.save(update_fields=["status", "completed_at", "error_message"])
        except Exception:
            pass  # run may have been deleted; nothing to do


# Assertions evaluated by fast regex/counter checks on the transcript.
HEURISTIC_ASSERTIONS = frozenset({
    "resolved_within_5_turns",
    "resolved_within_6_turns",
    "agent_acknowledges_frustration",
    "appointment_confirmed",
    "correct_date_time_captured",
    "contact_details_collected",
    "agent_provides_confirmation_number_or_summary",
    "agent_asks_for_clarification_when_unclear",
})

# Assertions that require understanding of intent/policy — evaluated by the LLM judge.
# runner sets passed=None; judge.evaluate_result fills them in.
SEMANTIC_ASSERTIONS = frozenset({
    "no_hallucinated_policy",
    "agent_does_not_promise_impossible_timeline",
    "agent_maintains_patience",
    "agent_does_not_fabricate_account_details",
})


def _evaluate_assertions(assertions, transcript, agent):
    agent_turns = [t["text"].lower() for t in transcript if t["speaker"] == "agent"]
    full_text = " ".join(agent_turns)
    results = []
    for a in assertions:
        if a in SEMANTIC_ASSERTIONS:
            results.append({"assertion": a, "passed": None, "semantic": True})
        else:
            results.append({"assertion": a, "passed": _check_assertion(a, transcript, full_text), "semantic": False})
    return results


def _check_assertion(assertion, transcript, full_agent_text):
    agent_turns = [t for t in transcript if t["speaker"] == "agent"]
    caller_turns = [t for t in transcript if t["speaker"] == "caller"]
    agent_count = len(agent_turns)
    all_text = " ".join(t["text"].lower() for t in transcript)

    if assertion == "resolved_within_5_turns":
        return agent_count <= 5
    if assertion == "resolved_within_6_turns":
        return agent_count <= 6
    if assertion == "agent_acknowledges_frustration":
        return any(w in full_agent_text for w in ["sorry", "understand", "apologize", "frustrat", "hear you", "i see"])
    if assertion == "appointment_confirmed":
        return any(w in full_agent_text for w in ["confirmed", "booked", "scheduled", "appointment", "see you"])
    if assertion == "correct_date_time_captured":
        import re
        time_pattern = re.compile(r"\b\d{1,2}(:\d{2})?\s*(am|pm)\b|\btuesday\b|\bwednesday\b|\bmonday\b|\bthursday\b|\bfriday\b")
        return bool(time_pattern.search(full_agent_text))
    if assertion == "contact_details_collected":
        # Check if the agent repeated back any name, email, or phone number from the transcript
        caller_text = " ".join(t["text"].lower() for t in caller_turns)
        import re
        phone = re.search(r"\b\d{3}[-.\s]\d{3}[-.\s]\d{4}\b", caller_text)
        email = re.search(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+", caller_text)
        if phone and phone.group() in full_agent_text:
            return True
        if email and email.group().lower() in full_agent_text:
            return True
        # Fall back to checking if agent acknowledged receiving details
        return any(w in full_agent_text for w in ["got it", "noted", "i have your", "i've noted", "thank you"]) and agent_count >= 2
    if assertion == "agent_provides_confirmation_number_or_summary":
        return any(w in full_agent_text for w in ["confirm", "reference", "summary", "to recap", "to confirm", "number"])
    if assertion == "agent_asks_for_clarification_when_unclear":
        return any(w in full_agent_text for w in ["could you", "can you", "please repeat", "clarif", "say that again", "didn't catch"])
    # Unknown assertion — default pass, semantic evaluation not configured
    return True
