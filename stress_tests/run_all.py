#!/usr/bin/env python3
"""Run all stress test tiers sequentially with summary reporting.

Usage:
    python stress_tests/run_all.py              # Run all tiers 1-5
    python stress_tests/run_all.py 1 3          # Run only tiers 1 and 3
    python stress_tests/run_all.py 1-3          # Run tiers 1 through 3
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from stress_tests.runner_helpers import print_summary, TierResult

TIER_MODULES = {
    1: "stress_tests.tier1_single_feature",
    2: "stress_tests.tier2_multi_feature",
    3: "stress_tests.tier3_new_module",
    4: "stress_tests.tier4_refactor_extend",
    5: "stress_tests.tier5_mini_browser",
    6: "stress_tests.tier6_rest_api",
    7: "stress_tests.tier7_plugin_system",
    8: "stress_tests.tier8_static_site_gen",
    9: "stress_tests.tier9_micro_framework",
    10: "stress_tests.tier10_text_browser",
    11: "stress_tests.mega1_project_management",
    12: "stress_tests.mega2_game_engine",
    13: "stress_tests.mega3_programming_language",
    14: "stress_tests.mega4_social_platform",
    15: "stress_tests.mega5_operating_system",
    16: "stress_tests.mega6_harness_clone",
}


def parse_tier_args(args: list[str]) -> list[int]:
    if not args:
        return list(TIER_MODULES.keys())

    tiers = set()
    skip_next = False
    for i, arg in enumerate(args):
        if skip_next:
            skip_next = False
            continue
        # Handle --tier N or --tier=N
        if arg == "--tier":
            if i + 1 < len(args):
                tiers.add(int(args[i + 1]))
                skip_next = True
            continue
        if arg.startswith("--tier="):
            tiers.add(int(arg.split("=", 1)[1]))
            continue
        # Skip unknown flags
        if arg.startswith("--"):
            continue
        # Handle ranges like 1-3
        if "-" in arg:
            start, end = arg.split("-", 1)
            tiers.update(range(int(start), int(end) + 1))
        else:
            tiers.add(int(arg))

    return sorted(t for t in tiers if t in TIER_MODULES)


async def main():
    tiers_to_run = parse_tier_args(sys.argv[1:])

    if not tiers_to_run:
        print(f"No valid tiers specified. Available: {min(TIER_MODULES)}-{max(TIER_MODULES)}")
        return 1

    print("=" * 70)
    print(f"  GRADUATED STRESS TEST SUITE — Tiers: {tiers_to_run}")
    print("=" * 70)

    results: list[TierResult] = []

    for tier_num in tiers_to_run:
        import importlib

        mod = importlib.import_module(TIER_MODULES[tier_num])
        mod.create_repo(mod.REPO_PATH, mod.SCAFFOLD_FILES)

        from stress_tests.runner_helpers import run_tier

        result = await run_tier(
            tier=tier_num,
            name=mod.__doc__.split("\n")[0].split(":")[1].strip() if mod.__doc__ else f"Tier {tier_num}",
            repo_path=mod.REPO_PATH,
            instructions=mod.INSTRUCTIONS,
            test_command=mod.TEST_COMMAND,
            worker_timeout=getattr(mod, "WORKER_TIMEOUT", 180),
            max_planner_turns=getattr(mod, "MAX_PLANNER_TURNS", 80),
            max_planner_wall_time=getattr(mod, "MAX_PLANNER_WALL_TIME", 900),
        )
        results.append(result)

    return print_summary(results)


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
