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
    / "crucible_cis_kali_debian_13"
)


class KaliCISMilestoneBBTests(
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
                "cis-debian-linux-13"
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
            "1.1.0",
        )


    def test_default_kali_profile_is_level1_workstation(
        self,
    ) -> None:

        plan = (
            build_hardening_plan(
                self.catalog,

                benchmark_id=(
                    "cis-debian-linux-13"
                ),

                machine_profile_id=(
                    "kali-rolling"
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
                    "cis-debian-linux-13"
                ),

                machine_profile_id=(
                    "kali-rolling"
                ),
            )
        )

        applicable = {
            control.id
            for control
            in plan.applicable_controls
        }

        groups = [
            set(plan.automated_control_ids),
            set(plan.conditional_control_ids),
            set(plan.audit_only_control_ids),
            set(plan.satisfied_elsewhere_control_ids),
            set(plan.manual_control_ids),
            set(plan.not_implemented_control_ids),
            set(plan.exception_control_ids),
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


    def test_role_exists(
        self,
    ) -> None:

        self.assertTrue(
            (
                ROLE_ROOT
                / "tasks"
                / "main.yml"
            ).is_file()
        )


    def test_kali_completion_marker_is_present(
        self,
    ) -> None:

        completion = (
            ROLE_ROOT
            / "tasks"
            / "completion.yml"
        )

        text = completion.read_text(
            encoding="utf-8"
        )

        self.assertIn(
            "/var/lib/crucible/hardening/kali-cis.yml",
            text,
        )

        self.assertNotIn(
            "/var/lib/crucible/hardening/ubuntu-cis.yml",
            text,
        )

    def test_kali_repository_https_controls_are_audit_only(
        self,
    ) -> None:

        for control_id in (
            "1.2.1.10",
            "1.2.1.11",
        ):

            control = (
                self.controls_by_id[
                    control_id
                ]
            )

            self.assertEqual(
                control.crucible_implementation,
                "audit_only",
            )

            self.assertIn(
                "kali-compatibility",
                control.tags,
            )

            self.assertIn(
                "vendor-policy-conflict",
                control.tags,
            )

    def test_aide_wrapper_is_migration_only(
        self,
    ) -> None:

        wave3_aide = (
            ROLE_ROOT
            / "tasks"
            / "wave3_aide.yml"
        )

        text = wave3_aide.read_text(
            encoding="utf-8"
        )

        self.assertEqual(
            text.count(
                "aide.wrapper"
            ),
            1,
        )

        self.assertIn(
            "'/usr/bin/aide.wrapper --check'",
            text,
        )

        self.assertIn(
            "- /usr/bin/aide",
            text,
        )

        self.assertIn(
            "- /usr/sbin/aideinit",
            text,
        )
    

if __name__ == "__main__":
    unittest.main()