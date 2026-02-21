import pytest

from harness.orchestration.reconcile import reconcile

pytestmark = [pytest.mark.e2e, pytest.mark.slow]


class TestReconciliation:
    @pytest.mark.asyncio
    async def test_reconcile_passes_when_tests_pass(self, tmp_path):
        script = tmp_path / "pass.sh"
        script.write_text("#!/bin/sh\nexit 0")
        script.chmod(0o755)

        report = await reconcile(
            repo_path=str(tmp_path),
            test_command=f"sh {script}",
            max_rounds=3,
        )

        assert report.final_verdict == "pass"
        assert report.rounds == 1

    @pytest.mark.asyncio
    async def test_reconcile_fails_when_tests_fail(self, tmp_path):
        script = tmp_path / "fail.sh"
        script.write_text("#!/bin/sh\necho FAIL\nexit 1")
        script.chmod(0o755)

        report = await reconcile(
            repo_path=str(tmp_path),
            test_command=f"sh {script}",
            max_rounds=1,
        )

        assert report.final_verdict == "fail"
        assert report.rounds == 1

    @pytest.mark.asyncio
    async def test_reconcile_retries_up_to_max_rounds(self, tmp_path):
        script = tmp_path / "fail.sh"
        script.write_text("#!/bin/sh\necho round-fail\nexit 1")
        script.chmod(0o755)

        report = await reconcile(
            repo_path=str(tmp_path),
            test_command=f"sh {script}",
            max_rounds=2,
        )

        assert report.final_verdict == "fail"
        assert report.rounds == 2

    @pytest.mark.asyncio
    async def test_reconcile_with_fixer(self, tmp_path):
        script = tmp_path / "fail.sh"
        script.write_text("#!/bin/sh\nexit 1")
        script.chmod(0o755)

        fixer_calls = []

        def fixer(failures):
            fixer_calls.append(failures)

        report = await reconcile(
            repo_path=str(tmp_path),
            test_command=f"sh {script}",
            max_rounds=2,
            spawn_fixer_fn=fixer,
        )

        assert report.fixes_attempted >= 1
        assert len(fixer_calls) >= 1

    @pytest.mark.asyncio
    async def test_reconcile_passes_after_fix(self, tmp_path):
        counter_file = tmp_path / "counter.txt"
        counter_file.write_text("0")

        script = tmp_path / "dynamic.sh"
        script.write_text(
            f'#!/bin/sh\nval=$(cat {counter_file})\nif [ "$val" -ge 1 ]; then exit 0; fi\necho fail\nexit 1\n'
        )
        script.chmod(0o755)

        def fixer(failures):
            counter_file.write_text("1")

        report = await reconcile(
            repo_path=str(tmp_path),
            test_command=f"sh {script}",
            max_rounds=3,
            spawn_fixer_fn=fixer,
        )

        assert report.final_verdict == "pass"
        assert report.rounds == 2
        assert report.fixes_attempted == 1
