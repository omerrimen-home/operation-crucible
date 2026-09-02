from pathlib import Path
import unittest

from crucible.hardening.catalog import (
    load_benchmark_controls,
    load_hardening_catalog,
)

from crucible.hardening.planner import (
    build_hardening_plan,
)


REPO_ROOT = (
    Path(__file__)
    .resolve()
    .parents[1]
)


HARDENING_CATALOG_PATH = (
    REPO_ROOT
    / "config"
    / "hardening.yml"
)


ROLE_ROOT = (
    REPO_ROOT
    / "ansible"
    / "roles"
    / "crucible_cis_ubuntu_26_04"
)


class UbuntuCISMilestoneBATests(
    unittest.TestCase
):

    @classmethod
    def setUpClass(
        cls,
    ) -> None:

        cls.catalog = (
            load_hardening_catalog(
                HARDENING_CATALOG_PATH,
                repo_root=REPO_ROOT,
            )
        )

        cls.benchmark = (
            cls.catalog.get(
                "cis-ubuntu-linux-26.04"
            )
        )

        cls.controls = (
            load_benchmark_controls(
                cls.benchmark
            )
        )

        cls.controls_by_id = {
            control.id: control
            for control
            in cls.controls
        }


    def test_benchmark_is_implemented(
        self,
    ) -> None:

        self.assertEqual(
            self.benchmark.status,
            "implemented",
        )

        self.assertEqual(
            self.benchmark.benchmark_version,
            "1.0.0",
        )


    def test_default_server_profile_is_level1(
        self,
    ) -> None:

        plan = (
            build_hardening_plan(
                self.catalog,

                benchmark_id=(
                    "cis-ubuntu-linux-26.04"
                ),

                machine_profile_id=(
                    "ubuntu-26.04-server"
                ),
            )
        )

        self.assertEqual(
            plan.profile.id,
            "level1-server",
        )


    def test_default_desktop_profile_is_level1(
        self,
    ) -> None:

        plan = (
            build_hardening_plan(
                self.catalog,

                benchmark_id=(
                    "cis-ubuntu-linux-26.04"
                ),

                machine_profile_id=(
                    "ubuntu-26.04-desktop"
                ),
            )
        )

        self.assertEqual(
            plan.profile.id,
            "level1-workstation",
        )


    def test_plan_classification_is_exhaustive(
        self,
    ) -> None:

        plan = (
            build_hardening_plan(
                self.catalog,

                benchmark_id=(
                    "cis-ubuntu-linux-26.04"
                ),

                machine_profile_id=(
                    "ubuntu-26.04-server"
                ),
            )
        )

        applicable = {
            control.id
            for control
            in plan.applicable_controls
        }

        groups = [
            set(
                plan.automated_control_ids
            ),

            set(
                plan.conditional_control_ids
            ),

            set(
                plan.audit_only_control_ids
            ),

            set(
                plan.satisfied_elsewhere_control_ids
            ),

            set(
                plan.manual_control_ids
            ),

            set(
                plan.not_implemented_control_ids
            ),

            set(
                plan.exception_control_ids
            ),
        ]

        classified = set().union(
            *groups
        )

        self.assertEqual(
            applicable,
            classified,
        )

        for index, left in enumerate(
            groups
        ):

            for right in groups[
                index + 1:
            ]:

                self.assertTrue(
                    left.isdisjoint(
                        right
                    )
                )


    def test_level2_server_contains_audit_controls(
        self,
    ) -> None:

        plan = (
            build_hardening_plan(
                self.catalog,

                benchmark_id=(
                    "cis-ubuntu-linux-26.04"
                ),

                machine_profile_id=(
                    "ubuntu-26.04-server"
                ),

                requested_profile=(
                    "level2-server"
                ),
            )
        )

        applicable = {
            control.id
            for control
            in plan.applicable_controls
        }

        self.assertIn(
            "6.2.1.1",
            applicable,
        )

        self.assertIn(
            "6.2.3.1",
            applicable,
        )


    def test_aide_controls_are_catalogued(
        self,
    ) -> None:

        self.assertIn(
            "6.3.1",
            self.controls_by_id,
        )

        self.assertIn(
            "6.3.2",
            self.controls_by_id,
        )


    def test_destructive_audit_controls_remain_deferred(
        self,
    ) -> None:

        for control_id in (
            "6.2.2.3",
            "6.2.3.35",
        ):

            control = (
                self.controls_by_id[
                    control_id
                ]
            )

            self.assertIn(
                "wave:deferred",
                control.tags,
            )


    def test_role_does_not_reference_legacy_aide_wrapper(
        self,
    ) -> None:

        occurrences: list[
            str
        ] = []

        for path in ROLE_ROOT.rglob(
            "*"
        ):

            if not path.is_file():
                continue

            if path.suffix not in {
                ".yml",
                ".yaml",
                ".j2",
                ".py",
            }:
                continue

            text = path.read_text(
                encoding="utf-8"
            )

            if "aide.wrapper" in text:

                occurrences.append(
                    str(
                        path.relative_to(
                            REPO_ROOT
                        )
                    )
                )

        self.assertEqual(
            occurrences,
            [],
        )


    def test_completion_marker_is_present(
        self,
    ) -> None:

        completion = (
            ROLE_ROOT
            / "tasks"
            / "completion.yml"
        )

        self.assertTrue(
            completion.is_file()
        )

        text = completion.read_text(
            encoding="utf-8"
        )

        self.assertIn(
            "/var/lib/crucible/hardening/ubuntu-cis.yml",
            text,
        )

        self.assertIn(
            "'unverified'",
            text,
        )


if __name__ == "__main__":
    unittest.main()