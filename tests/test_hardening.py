import tempfile
import unittest
from pathlib import Path

import yaml

from crucible.hardening.catalog import (
    HardeningCatalogError,
    load_hardening_catalog,
)

from crucible.hardening.planner import (
    HardeningPlanningError,
    build_hardening_plan,
)


class HardeningFrameworkTests(
    unittest.TestCase
):

    def _write_yaml(
        self,
        path: Path,
        data: dict,
    ) -> None:

        path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        with path.open(
            "w",
            encoding="utf-8",
        ) as handle:

            yaml.safe_dump(
                data,
                handle,
                sort_keys=False,
            )


    def _create_fixture(
        self,
        root: Path,
    ) -> Path:

        controls_path = (
            root
            / "hardening"
            / "benchmarks"
            / "test-benchmark.yml"
        )

        self._write_yaml(
            controls_path,
            {
                "schema_version": 1,

                "benchmark_id": (
                    "test-linux"
                ),

                "benchmark_version": (
                    "1.0"
                ),

                "controls": {
                    "1.1.1": {
                        "title": (
                            "Automated control"
                        ),

                        "profiles": [
                            "level1-server",
                        ],

                        "assessment": (
                            "automated"
                        ),

                        "crucible_implementation": (
                            "automated"
                        ),

                        "tags": [
                            "filesystem",
                        ],
                    },

                    "1.1.2": {
                        "title": (
                            "Manual control"
                        ),

                        "profiles": [
                            "level1-server",
                        ],

                        "assessment": (
                            "manual"
                        ),

                        "crucible_implementation": (
                            "manual"
                        ),

                        "tags": [],
                    },

                    "1.1.3": {
                        "title": (
                            "Unimplemented control"
                        ),

                        "profiles": [
                            "level1-server",
                        ],

                        "assessment": (
                            "automated"
                        ),

                        "crucible_implementation": (
                            "not_implemented"
                        ),

                        "tags": [],
                    },
                    "2.1.4": {
                        "title": (
                            "DNS server not in use"
                        ),

                        "profiles": [
                            "level1-server",
                        ],

                        "assessment": (
                            "automated"
                        ),

                        "crucible_implementation": (
                            "conditional"
                        ),

                        "tags": [
                            "wave:1",
                            (
                                "preserve-if-capability:"
                                "service:dns-server"
                            ),
                        ],
                    },
                },
            },
        )

        catalog_path = (
            root
            / "config"
            / "hardening.yml"
        )

        self._write_yaml(
            catalog_path,
            {
                "schema_version": 1,

                "benchmarks": {
                    "test-linux": {
                        "display_name": (
                            "Test Linux Benchmark"
                        ),

                        "description": (
                            "Test benchmark"
                        ),

                        "authority": (
                            "Test"
                        ),

                        "benchmark_version": (
                            "1.0"
                        ),

                        "status": (
                            "implemented"
                        ),

                        "target": {
                            "type": "os",

                            "supported_profiles": [
                                "test-server",
                            ],
                        },

                        "profiles": {
                            "level1-server": {
                                "display_name": (
                                    "Level 1 Server"
                                ),

                                "description": (
                                    "Test profile"
                                ),

                                "applies_to_profiles": [
                                    "test-server",
                                ],

                                "default_for_profiles": [
                                    "test-server",
                                ],
                            },
                        },

                        "controls_file": (
                            "hardening/benchmarks/"
                            "test-benchmark.yml"
                        ),
                    },
                },
            },
        )

        return catalog_path


    def test_capability_creates_derived_exception(
        self,
    ):

        with tempfile.TemporaryDirectory() as temp:

            root = Path(
                temp
            )

            catalog = (
                load_hardening_catalog(
                    self._create_fixture(
                        root
                    ),
                    repo_root=root,
                )
            )

            plan = (
                build_hardening_plan(
                    catalog,
                    benchmark_id=(
                        "test-linux"
                    ),
                    machine_profile_id=(
                        "test-server"
                    ),
                    capabilities=[
                        "service:dns-server",
                    ],
                )
            )

            self.assertIn(
                "2.1.4",
                plan
                .derived_exception_control_ids,
            )

            self.assertIn(
                "2.1.4",
                plan
                .exception_control_ids,
            )

            self.assertNotIn(
                "2.1.4",
                plan
                .conditional_control_ids,
            )

            self.assertIn(
                "service:dns-server",
                plan
                .derived_exception_reasons[
                    "2.1.4"
                ],
            )


    def test_conditional_control_remains_without_capability(
        self,
    ):

        with tempfile.TemporaryDirectory() as temp:

            root = Path(
                temp
            )

            catalog = (
                load_hardening_catalog(
                    self._create_fixture(
                        root
                    ),
                    repo_root=root,
                )
            )

            plan = (
                build_hardening_plan(
                    catalog,
                    benchmark_id=(
                        "test-linux"
                    ),
                    machine_profile_id=(
                        "test-server"
                    ),
                )
            )

            self.assertIn(
                "2.1.4",
                plan
                .conditional_control_ids,
            )

            self.assertNotIn(
                "2.1.4",
                plan
                .exception_control_ids,
            )



    def test_implemented_benchmark_builds_plan(
        self,
    ):

        with tempfile.TemporaryDirectory() as temp:

            root = Path(
                temp
            )

            catalog_path = (
                self._create_fixture(
                    root
                )
            )

            catalog = (
                load_hardening_catalog(
                    catalog_path,
                    repo_root=root,
                )
            )

            plan = (
                build_hardening_plan(
                    catalog,
                    benchmark_id=(
                        "test-linux"
                    ),
                    machine_profile_id=(
                        "test-server"
                    ),
                )
            )

            self.assertEqual(
                plan.profile.id,
                "level1-server",
            )

            self.assertEqual(
                plan.automated_control_ids,
                (
                    "1.1.1",
                ),
            )

            self.assertEqual(
                plan.manual_control_ids,
                (
                    "1.1.2",
                ),
            )

            self.assertEqual(
                plan.not_implemented_control_ids,
                (
                    "1.1.3",
                ),
            )


    def test_exception_removes_automated_control(
        self,
    ):

        with tempfile.TemporaryDirectory() as temp:

            root = Path(
                temp
            )

            catalog = (
                load_hardening_catalog(
                    self._create_fixture(
                        root
                    ),
                    repo_root=root,
                )
            )

            plan = (
                build_hardening_plan(
                    catalog,
                    benchmark_id=(
                        "test-linux"
                    ),
                    machine_profile_id=(
                        "test-server"
                    ),
                    exceptions=[
                        "1.1.1",
                    ],
                )
            )

            self.assertEqual(
                plan.automated_control_ids,
                (),
            )

            self.assertEqual(
                plan.exception_control_ids,
                (
                    "1.1.1",
                ),
            )


    def test_unknown_exception_rejected(
        self,
    ):

        with tempfile.TemporaryDirectory() as temp:

            root = Path(
                temp
            )

            catalog = (
                load_hardening_catalog(
                    self._create_fixture(
                        root
                    ),
                    repo_root=root,
                )
            )

            with self.assertRaises(
                HardeningPlanningError
            ):

                build_hardening_plan(
                    catalog,
                    benchmark_id=(
                        "test-linux"
                    ),
                    machine_profile_id=(
                        "test-server"
                    ),
                    exceptions=[
                        "99.99.99",
                    ],
                )


    def test_incompatible_os_profile_rejected(
        self,
    ):

        with tempfile.TemporaryDirectory() as temp:

            root = Path(
                temp
            )

            catalog = (
                load_hardening_catalog(
                    self._create_fixture(
                        root
                    ),
                    repo_root=root,
                )
            )

            with self.assertRaises(
                HardeningPlanningError
            ):

                build_hardening_plan(
                    catalog,
                    benchmark_id=(
                        "test-linux"
                    ),
                    machine_profile_id=(
                        "windows-11"
                    ),
                )


    def test_planned_benchmark_cannot_execute(
        self,
    ):

        with tempfile.TemporaryDirectory() as temp:

            root = Path(
                temp
            )

            catalog_path = (
                root
                / "config"
                / "hardening.yml"
            )

            self._write_yaml(
                catalog_path,
                {
                    "schema_version": 1,

                    "benchmarks": {
                        "planned": {
                            "display_name": (
                                "Planned Benchmark"
                            ),

                            "description": (
                                "Not implemented"
                            ),

                            "authority": (
                                "Test"
                            ),

                            "benchmark_version": (
                                "1.0"
                            ),

                            "status": (
                                "planned"
                            ),

                            "target": {
                                "type": "os",

                                "supported_profiles": [
                                    "test-server",
                                ],
                            },

                            "profiles": {},

                            "controls_file": None,
                        },
                    },
                },
            )

            catalog = (
                load_hardening_catalog(
                    catalog_path,
                    repo_root=root,
                )
            )

            with self.assertRaises(
                HardeningPlanningError
            ):

                build_hardening_plan(
                    catalog,
                    benchmark_id="planned",
                    machine_profile_id=(
                        "test-server"
                    ),
                )


if __name__ == "__main__":
    unittest.main()