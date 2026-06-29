"""
Standalone entrypoint for the scenario caller bot.
Run as a subprocess so Daily SDK is isolated from the Pipecat pipeline process.

Usage:
    python caller_bot_main.py <room_url> <room_token> <steps_json>

Outputs: JSON array of transcript turns on stdout.
"""
import asyncio
import json
import sys


async def main():
    if len(sys.argv) != 4:
        print(json.dumps({"error": "Usage: caller_bot_main.py <room_url> <room_token> <steps_json>"}))
        sys.exit(1)

    room_url = sys.argv[1]
    room_token = sys.argv[2]
    steps = json.loads(sys.argv[3])

    from daily import Daily
    Daily.init()

    from caller_bot import ScenarioCallerBot
    bot = ScenarioCallerBot(room_url=room_url, room_token=room_token, steps=steps)
    transcript = await bot.run()

    Daily.deinit()
    print(json.dumps(transcript))


if __name__ == "__main__":
    asyncio.run(main())
