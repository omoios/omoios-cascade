import os

from harness.orchestration.reconcile import reconcile


class TestReconciliation:
    async def test_green_on_first_try(self, tmp_path):
        report = await reconcile(repo_path=str(tmp_path), test_command="exit 0")

        assert report.final_verdict == "pass"
        assert report.rounds == 1

    async def test_fixer_spawned_on_failure(self, tmp_path):
        calls: list[list[str]] = []

        def fixer(failures_found: list[str]) -> None:
            calls.append(list(failures_found))

        report = await reconcile(
            repo_path=str(tmp_path),
            test_command="exit 1",
            max_rounds=1,
            spawn_fixer_fn=fixer,
        )

        assert report.final_verdict == "fail"
        assert len(calls) == 1

    async def test_respects_max_rounds_cap(self, tmp_path):
        report = await reconcile(repo_path=str(tmp_path), test_command="exit 1", max_rounds=2)

        assert report.rounds == 2
        assert report.final_verdict == "fail"

    async def test_final_verdict_pass_after_fix(self, tmp_path):
        counter_file = tmp_path / "run_count"
        script = tmp_path / "test.sh"
        script.write_text(
            "#!/bin/bash\n"
            f"count=$(cat {counter_file} 2>/dev/null || echo 0)\n"
            "count=$((count + 1))\n"
            f"echo $count > {counter_file}\n"
            "if [ $count -ge 2 ]; then exit 0; else exit 1; fi"
        )
        os.chmod(script, 0o755)

        report = await reconcile(repo_path=str(tmp_path), test_command=f"{script}", max_rounds=3)

        assert report.final_verdict == "pass"
        assert report.rounds == 2

    async def test_final_verdict_fail_when_exhausted(self, tmp_path):
        report = await reconcile(repo_path=str(tmp_path), test_command="exit 1", max_rounds=3)

        assert report.final_verdict == "fail"

    async def test_green_commit_set_on_success(self, tmp_path):
        report = await reconcile(repo_path=str(tmp_path), test_command="exit 0")

        assert report.final_verdict == "pass"
        assert report.green_commit is not None
