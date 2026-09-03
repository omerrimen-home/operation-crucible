from __future__ import annotations

from collections import Counter
from pathlib import Path
import unittest

import yaml

from crucible.hardening.capabilities import (
    derive_machine_hardening_capabilities,
)

from crucible.hardening.catalog import (
    load_benchmark_controls,
    load_hardening_catalog,
)

from crucible.hardening.planner import (
    build_hardening_plan,
)

from tools.implement_windows10_cis_bc_g import (
    REGISTRY_POLICY_OVERRIDES,
    descriptor_for_location,
    extract_registry_locations,
    parse_location,
    registry_entries_for_control,
)


# ============================================================
# Repository paths
# ============================================================

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


WINDOWS10_PROFILE_PATH = (
    REPO_ROOT
    / "profiles"
    / "os"
    / "windows-10.yml"
)


ROLE_ROOT = (
    REPO_ROOT
    / "ansible"
    / "roles"
    / "crucible_cis_windows_10_standalone"
)


TASK_ROOT = (
    ROLE_ROOT
    / "tasks"
)


VARS_ROOT = (
    ROLE_ROOT
    / "vars"
)


# ============================================================
# Benchmark invariants
# ============================================================

BENCHMARK_ID = (
    "cis-microsoft-windows-10-standalone"
)

BENCHMARK_VERSION = "4.0.0"

TOTAL_CONTROL_COUNT = 494


SOURCE_PROFILE_COUNTS = {

    "level1": 333,

    "level2": 104,

    "bitlocker": 44,

    "next-generation": 13,
}


SOURCE_ASSESSMENT_COUNTS = {

    "automated": 492,

    "manual": 2,
}


MANUAL_CONTROL_IDS = {

    "1.2.3",

    "2.3.11.6",
}


AUDIT_ONLY_CONTROL_IDS = {

    "2.2.29",
}


CONDITIONAL_CONTROL_IDS = {

    # BC-D parameterized built-in account renames.
    "2.3.1.4",
    "2.3.1.5",

    # BC-G management-sensitive controls.
    "5.41",
    "18.10.89.2.2",
    "18.10.90.1",
}


MANAGEMENT_SENSITIVE_CONTROL_IDS = {

    "5.41",

    "18.10.89.2.2",

    "18.10.90.1",
}


EXPECTED_PROFILE_COUNTS = {

    "level1":
        333,

    "level1-bitlocker":
        377,

    "level1-next-generation":
        346,

    "level1-bitlocker-next-generation":
        390,

    "level2":
        437,

    "level2-bitlocker":
        481,

    "level2-next-generation":
        450,

    "level2-bitlocker-next-generation":
        494,

    "bitlocker":
        44,

    "next-generation":
        13,
}


EXPECTED_PROFILES = {

    "level1",

    "level1-bitlocker",

    "level1-next-generation",

    "level1-bitlocker-next-generation",

    "level2",

    "level2-bitlocker",

    "level2-next-generation",

    "level2-bitlocker-next-generation",

    "bitlocker",

    "next-generation",
}


# ============================================================
# BC-C
# ============================================================

BC_C_ACCOUNT_POLICY_AUTOMATED_IDS = {

    "1.1.1",
    "1.1.2",
    "1.1.3",
    "1.1.4",
    "1.1.5",
    "1.1.6",
    "1.1.7",

    "1.2.1",
    "1.2.2",
    "1.2.4",
}


BC_C_USER_RIGHT_AUTOMATED_IDS = {

    f"2.2.{index}"

    for index
    in range(
        1,
        40,
    )

} - {

    "2.2.29",
}


BC_C_AUTOMATED_IDS = (
    BC_C_ACCOUNT_POLICY_AUTOMATED_IDS
    |
    BC_C_USER_RIGHT_AUTOMATED_IDS
)


BC_C_GUEST_INCLUDE_IDS = {

    "2.2.16",
    "2.2.17",
    "2.2.18",
    "2.2.19",
    "2.2.20",
}


# ============================================================
# BC-D
# ============================================================

BC_D_RENAME_IDS = {

    "2.3.1.4",

    "2.3.1.5",
}


BC_D_PREVIOUSLY_DEFERRED_IDS = {

    # Level 2 Security Options, completed in BC-G.
    "2.3.4.1",
    "2.3.14.1",

    # BitLocker Security Option, completed in BC-H.
    "2.3.7.3",
}


BC_D_MANUAL_ID = "2.3.11.6"


BC_D_NTLM_MANAGEMENT_VALIDATION_IDS = {

    "2.3.11.7",

    "2.3.11.9",

    "2.3.11.10",
}


# ============================================================
# BC-E
# ============================================================

BC_E_LEVEL1_SERVICE_IDS = {

    "5.3",

    "5.7",
    "5.8",
    "5.9",

    "5.11",
    "5.12",
    "5.14",

    "5.25",
    "5.27",
    "5.29",

    "5.31",
    "5.32",
    "5.33",
    "5.34",

    "5.37",
    "5.38",

    "5.43",
    "5.44",
    "5.45",
    "5.46",
    "5.47",
}


BC_E_FIREWALL_IDS = (

    {

        f"9.2.{number}"

        for number
        in range(
            1,
            8,
        )
    }

    |

    {

        f"9.3.{number}"

        for number
        in range(
            1,
            8,
        )
    }
)


BC_E_AUDIT_IDS = {

    "17.1.1",

    "17.2.1",
    "17.2.2",
    "17.2.3",

    "17.3.1",
    "17.3.2",

    "17.5.1",
    "17.5.2",
    "17.5.3",
    "17.5.4",
    "17.5.5",
    "17.5.6",

    "17.6.1",
    "17.6.2",
    "17.6.3",
    "17.6.4",

    "17.7.1",
    "17.7.2",
    "17.7.3",
    "17.7.4",
    "17.7.5",

    "17.8.1",

    "17.9.1",
    "17.9.2",
    "17.9.3",
    "17.9.4",
    "17.9.5",
}


# ============================================================
# BC-F
# ============================================================

BC_F_EVENT_LOG_IDS = {

    "18.10.26.1.1",
    "18.10.26.1.2",

    "18.10.26.2.1",
    "18.10.26.2.2",

    "18.10.26.3.1",
    "18.10.26.3.2",

    "18.10.26.4.1",
    "18.10.26.4.2",
}


BC_F_DEFENDER_LEVEL1_IDS = {

    "18.10.43.4.1",

    "18.10.43.5.1",

    "18.10.43.6.1.1",
    "18.10.43.6.1.2",

    "18.10.43.6.3.1",

    "18.10.43.7.1",

    "18.10.43.10.1",
    "18.10.43.10.2",
    "18.10.43.10.3",
    "18.10.43.10.4",
    "18.10.43.10.5",

    "18.10.43.11.1.1.2",

    "18.10.43.13.1",
    "18.10.43.13.2",
    "18.10.43.13.3",
    "18.10.43.13.4",
    "18.10.43.13.5",

    "18.10.43.16",
    "18.10.43.17",
}


BC_F_DEFENDER_LEVEL2_IDS = {

    "18.10.43.5.2",

    "18.10.43.8.1",

    "18.10.43.11.1.1.1",

    "18.10.43.11.1.2.1",

    "18.10.43.12.1",
}


# ============================================================
# BC-G
# ============================================================

BC_G_MANAGEMENT_SENSITIVE_IDS = {

    "5.41",

    "18.10.89.2.2",

    "18.10.90.1",
}


# ============================================================
# BC-H
# ============================================================

BC_H_BITLOCKER_COUNT = 44

BC_H_NEXT_GENERATION_COUNT = 13

BC_H_ADVANCED_COUNT = 57


# ============================================================
# Helpers
# ============================================================

def load_yaml_file(
    path: Path,
):
    return yaml.safe_load(
        path.read_text(
            encoding="utf-8",
        )
    )


def implementation_counts(
    controls,
) -> Counter:

    return Counter(

        control.crucible_implementation

        for control
        in controls
    )


# ============================================================
# Test class
# ============================================================

class Windows10CISMilestoneBCITests(
    unittest.TestCase
):

    @classmethod
    def setUpClass(
        cls,
    ) -> None:

        cls.catalog = (
            load_hardening_catalog(
                HARDENING_CATALOG_PATH,

                repo_root=(
                    REPO_ROOT
                ),
            )
        )


        cls.benchmark = (
            cls.catalog.get(
                BENCHMARK_ID
            )
        )


        cls.controls = (
            load_benchmark_controls(
                cls.benchmark
            )
        )


        cls.controls_by_id = {

            control.id:
                control

            for control
            in cls.controls
        }


        cls.windows10_profile = (
            load_yaml_file(
                WINDOWS10_PROFILE_PATH
            )
        )


    # ========================================================
    # Benchmark identity / source inventory
    # ========================================================

    def test_benchmark_is_implemented(
        self,
    ) -> None:

        self.assertEqual(
            self.benchmark.status,
            "implemented",
        )


        self.assertEqual(
            self.benchmark.benchmark_version,
            BENCHMARK_VERSION,
        )


    def test_complete_494_control_inventory(
        self,
    ) -> None:

        self.assertEqual(
            len(
                self.controls
            ),
            TOTAL_CONTROL_COUNT,
        )


    def test_control_ids_are_unique(
        self,
    ) -> None:

        ids = [

            control.id

            for control
            in self.controls
        ]


        self.assertEqual(
            len(ids),
            len(set(ids)),
        )


    def test_source_assessment_counts(
        self,
    ) -> None:

        counts = Counter(

            control.assessment

            for control
            in self.controls
        )


        self.assertEqual(
            counts["automated"],
            SOURCE_ASSESSMENT_COUNTS[
                "automated"
            ],
        )


        self.assertEqual(
            counts["manual"],
            SOURCE_ASSESSMENT_COUNTS[
                "manual"
            ],
        )


    def test_manual_source_control_ids(
        self,
    ) -> None:

        actual = {

            control.id

            for control
            in self.controls

            if (
                control.assessment
                ==
                "manual"
            )
        }


        self.assertEqual(
            actual,
            MANUAL_CONTROL_IDS,
        )


    def test_source_profile_counts(
        self,
    ) -> None:

        counts = Counter()


        for control in self.controls:

            for tag in control.tags:

                if (
                    tag
                    ==
                    "source-profile:level1"
                ):

                    counts["level1"] += 1


                elif (
                    tag
                    ==
                    "source-profile:level2"
                ):

                    counts["level2"] += 1


                elif (
                    tag
                    ==
                    "source-profile:bitlocker"
                ):

                    counts["bitlocker"] += 1


                elif (
                    tag
                    ==
                    "source-profile:next-generation"
                ):

                    counts[
                        "next-generation"
                    ] += 1


        self.assertEqual(
            dict(counts),
            SOURCE_PROFILE_COUNTS,
        )


    def test_expected_profiles_exist(
        self,
    ) -> None:

        self.assertEqual(
            set(
                self.benchmark.profiles
            ),
            EXPECTED_PROFILES,
        )


    def test_default_profile_is_level1(
        self,
    ) -> None:

        plan = (
            build_hardening_plan(
                self.catalog,

                benchmark_id=(
                    BENCHMARK_ID
                ),

                machine_profile_id=(
                    "windows-10"
                ),
            )
        )


        self.assertEqual(
            plan.profile.id,
            "level1",
        )


    def test_effective_profile_membership_counts(
        self,
    ) -> None:

        for (
            profile_id,
            expected_count,
        ) in (
            EXPECTED_PROFILE_COUNTS
            .items()
        ):

            with self.subTest(
                profile=profile_id
            ):

                plan = (
                    build_hardening_plan(
                        self.catalog,

                        benchmark_id=(
                            BENCHMARK_ID
                        ),

                        machine_profile_id=(
                            "windows-10"
                        ),

                        requested_profile=(
                            profile_id
                        ),
                    )
                )


                self.assertEqual(
                    len(
                        plan.applicable_controls
                    ),
                    expected_count,
                )


    # ========================================================
    # Final BC-H / BC-I classification
    # ========================================================

    def test_final_global_implementation_counts(
        self,
    ) -> None:

        counts = (
            implementation_counts(
                self.controls
            )
        )


        self.assertEqual(
            counts["automated"],
            486,
        )


        self.assertEqual(
            counts["conditional"],
            5,
        )


        self.assertEqual(
            counts["audit_only"],
            1,
        )


        self.assertEqual(
            counts["manual"],
            2,
        )


        self.assertEqual(
            counts.get(
                "not_implemented",
                0,
            ),
            0,
        )


        self.assertEqual(
            sum(
                counts.values()
            ),
            TOTAL_CONTROL_COUNT,
        )


    def test_no_control_is_not_implemented(
        self,
    ) -> None:

        unresolved = {

            control.id

            for control
            in self.controls

            if (
                control.crucible_implementation
                ==
                "not_implemented"
            )
        }


        self.assertEqual(
            unresolved,
            set(),
        )


    def test_exact_manual_implementation_controls(
        self,
    ) -> None:

        actual = {

            control.id

            for control
            in self.controls

            if (
                control.crucible_implementation
                ==
                "manual"
            )
        }


        self.assertEqual(
            actual,
            MANUAL_CONTROL_IDS,
        )


    def test_exact_audit_only_controls(
        self,
    ) -> None:

        actual = {

            control.id

            for control
            in self.controls

            if (
                control.crucible_implementation
                ==
                "audit_only"
            )
        }


        self.assertEqual(
            actual,
            AUDIT_ONLY_CONTROL_IDS,
        )


    def test_exact_conditional_controls(
        self,
    ) -> None:

        actual = {

            control.id

            for control
            in self.controls

            if (
                control.crucible_implementation
                ==
                "conditional"
            )
        }


        self.assertEqual(
            actual,
            CONDITIONAL_CONTROL_IDS,
        )


    # ========================================================
    # Planner invariants
    # ========================================================

    def test_every_profile_has_zero_not_implemented_controls(
        self,
    ) -> None:

        for profile_id in (
            self.benchmark.profiles
        ):

            with self.subTest(
                profile=profile_id
            ):

                plan = (
                    build_hardening_plan(
                        self.catalog,

                        benchmark_id=(
                            BENCHMARK_ID
                        ),

                        machine_profile_id=(
                            "windows-10"
                        ),

                        requested_profile=(
                            profile_id
                        ),

                        capabilities=[
                            "management:winrm",
                        ],
                    )
                )


                self.assertEqual(
                    set(
                        plan.not_implemented_control_ids
                    ),
                    set(),
                )


    def test_plan_classification_is_exhaustive_and_disjoint(
        self,
    ) -> None:

        for profile_id in (
            self.benchmark.profiles
        ):

            with self.subTest(
                profile=profile_id
            ):

                plan = (
                    build_hardening_plan(
                        self.catalog,

                        benchmark_id=(
                            BENCHMARK_ID
                        ),

                        machine_profile_id=(
                            "windows-10"
                        ),

                        requested_profile=(
                            profile_id
                        ),

                        capabilities=[
                            "management:winrm",
                        ],
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


                for (
                    index,
                    left,
                ) in enumerate(
                    groups
                ):

                    for right in groups[
                        index
                        +
                        1:
                    ]:

                        self.assertTrue(
                            left.isdisjoint(
                                right
                            )
                        )


    # ========================================================
    # Machine capabilities / WinRM exceptions
    # ========================================================

    def test_windows_profile_exposes_management_capabilities(
        self,
    ) -> None:

        capabilities = (
            derive_machine_hardening_capabilities(
                self.windows10_profile
            )
        )


        self.assertIn(
            "management:psrp",
            capabilities,
        )


        self.assertIn(
            "management:https",
            capabilities,
        )


        self.assertIn(
            "management:winrm",
            capabilities,
        )


    def test_management_sensitive_controls_are_tagged(
        self,
    ) -> None:

        for control_id in (
            MANAGEMENT_SENSITIVE_CONTROL_IDS
        ):

            control = (
                self.controls_by_id[
                    control_id
                ]
            )


            self.assertEqual(
                control.crucible_implementation,
                "conditional",
            )


            self.assertIn(
                "management-sensitive",
                control.tags,
            )


            self.assertIn(
                (
                    "preserve-if-capability:"
                    "management:winrm"
                ),
                control.tags,
            )


    def test_level2_winrm_controls_become_derived_exceptions(
        self,
    ) -> None:

        plan = (
            build_hardening_plan(
                self.catalog,

                benchmark_id=(
                    BENCHMARK_ID
                ),

                machine_profile_id=(
                    "windows-10"
                ),

                requested_profile=(
                    "level2"
                ),

                capabilities=[
                    "management:winrm",
                ],
            )
        )


        for control_id in (
            MANAGEMENT_SENSITIVE_CONTROL_IDS
        ):

            self.assertIn(
                control_id,
                plan.derived_exception_control_ids,
            )


            self.assertIn(
                control_id,
                plan.exception_control_ids,
            )


    def test_level2_without_winrm_capability_keeps_management_controls(
        self,
    ) -> None:

        plan = (
            build_hardening_plan(
                self.catalog,

                benchmark_id=(
                    BENCHMARK_ID
                ),

                machine_profile_id=(
                    "windows-10"
                ),

                requested_profile=(
                    "level2"
                ),
            )
        )


        for control_id in (
            MANAGEMENT_SENSITIVE_CONTROL_IDS
        ):

            self.assertIn(
                control_id,
                plan.conditional_control_ids,
            )


            self.assertNotIn(
                control_id,
                plan.exception_control_ids,
            )


    # ========================================================
    # BC-C
    # ========================================================

    def test_bc_c_has_48_automated_controls(
        self,
    ) -> None:

        self.assertEqual(
            len(
                BC_C_AUTOMATED_IDS
            ),
            48,
        )


        for control_id in (
            BC_C_AUTOMATED_IDS
        ):

            self.assertEqual(
                self.controls_by_id[
                    control_id
                ].crucible_implementation,
                "automated",
            )


    def test_bc_c_account_policy_controls_are_implemented(
        self,
    ) -> None:

        for control_id in (
            BC_C_ACCOUNT_POLICY_AUTOMATED_IDS
        ):

            control = (
                self.controls_by_id[
                    control_id
                ]
            )


            self.assertIn(
                "wave:1",
                control.tags,
            )


    def test_bc_c_user_right_controls_use_user_right_backend(
        self,
    ) -> None:

        for control_id in (
            BC_C_USER_RIGHT_AUTOMATED_IDS
        ):

            control = (
                self.controls_by_id[
                    control_id
                ]
            )


            self.assertIn(
                "area:user-rights",
                control.tags,
            )


            self.assertIn(
                "backend:user-rights",
                control.tags,
            )


    def test_bc_c_guest_deny_rights_preserve_include_semantics(
        self,
    ) -> None:

        for control_id in (
            BC_C_GUEST_INCLUDE_IDS
        ):

            self.assertIn(
                "assignment:include",
                self.controls_by_id[
                    control_id
                ].tags,
            )


    def test_bc_c_service_logon_right_remains_audit_only(
        self,
    ) -> None:

        control = (
            self.controls_by_id[
                "2.2.29"
            ]
        )


        self.assertEqual(
            control.crucible_implementation,
            "audit_only",
        )


        self.assertIn(
            "site-policy-dependent",
            control.tags,
        )


        self.assertIn(
            "service-account-aware",
            control.tags,
        )


    def test_bc_c_administrator_lockout_remains_manual(
        self,
    ) -> None:

        control = (
            self.controls_by_id[
                "1.2.3"
            ]
        )


        self.assertEqual(
            control.assessment,
            "manual",
        )


        self.assertEqual(
            control.crucible_implementation,
            "manual",
        )


    # ========================================================
    # BC-D
    # ========================================================

    def test_bc_d_account_renames_are_conditional(
        self,
    ) -> None:

        for control_id in (
            BC_D_RENAME_IDS
        ):

            control = (
                self.controls_by_id[
                    control_id
                ]
            )


            self.assertEqual(
                control.crucible_implementation,
                "conditional",
            )


            self.assertIn(
                "parameterized",
                control.tags,
            )


            self.assertIn(
                "identity-sensitive",
                control.tags,
            )


    def test_bc_d_previously_deferred_security_options_are_now_complete(
        self,
    ) -> None:

        for control_id in (
            BC_D_PREVIOUSLY_DEFERRED_IDS
        ):

            self.assertEqual(
                self.controls_by_id[
                    control_id
                ].crucible_implementation,
                "automated",
            )


    def test_bc_d_force_logoff_remains_manual(
        self,
    ) -> None:

        control = (
            self.controls_by_id[
                BC_D_MANUAL_ID
            ]
        )


        self.assertEqual(
            control.assessment,
            "manual",
        )


        self.assertEqual(
            control.crucible_implementation,
            "manual",
        )


    def test_bc_d_ntlm_controls_require_management_validation(
        self,
    ) -> None:

        for control_id in (
            BC_D_NTLM_MANAGEMENT_VALIDATION_IDS
        ):

            self.assertIn(
                "management-validation-required",
                self.controls_by_id[
                    control_id
                ].tags,
            )


    def test_bc_d_registry_policy_inventory_has_51_entries(
        self,
    ) -> None:

        data = load_yaml_file(
            VARS_ROOT
            / "security_options.yml"
        )


        policies = data[
            "crucible_cis_windows_10_security_option_registry_policies"
        ]


        self.assertEqual(
            len(
                policies
            ),
            51,
        )


        ids = [

            policy[
                "control_id"
            ]

            for policy
            in policies
        ]


        self.assertEqual(
            len(ids),
            len(set(ids)),
        )


    # ========================================================
    # BC-E
    # ========================================================

    def test_bc_e_has_21_level1_service_controls(
        self,
    ) -> None:

        self.assertEqual(
            len(
                BC_E_LEVEL1_SERVICE_IDS
            ),
            21,
        )


        for control_id in (
            BC_E_LEVEL1_SERVICE_IDS
        ):

            self.assertEqual(
                self.controls_by_id[
                    control_id
                ].crucible_implementation,
                "automated",
            )


    def test_bc_e_has_14_firewall_controls(
        self,
    ) -> None:

        self.assertEqual(
            len(
                BC_E_FIREWALL_IDS
            ),
            14,
        )


        for control_id in (
            BC_E_FIREWALL_IDS
        ):

            self.assertEqual(
                self.controls_by_id[
                    control_id
                ].crucible_implementation,
                "automated",
            )


    def test_bc_e_has_27_advanced_audit_controls(
        self,
    ) -> None:

        self.assertEqual(
            len(
                BC_E_AUDIT_IDS
            ),
            27,
        )


        for control_id in (
            BC_E_AUDIT_IDS
        ):

            control = (
                self.controls_by_id[
                    control_id
                ]
            )


            self.assertEqual(
                control.crucible_implementation,
                "automated",
            )


            self.assertIn(
                "backend:auditpol",
                control.tags,
            )


    def test_bc_e_service_inventory_is_complete(
        self,
    ) -> None:

        data = load_yaml_file(
            VARS_ROOT
            / "services.yml"
        )


        level1 = data[
            "crucible_cis_windows_10_level1_services"
        ]


        level2 = data[
            "crucible_cis_windows_10_level2_services"
        ]


        self.assertEqual(
            len(level1),
            21,
        )


        self.assertEqual(
            len(level2),
            26,
        )


        all_ids = {

            item[
                "control_id"
            ]

            for item
            in (
                level1
                +
                level2
            )
        }


        self.assertEqual(
            len(
                all_ids
            ),
            47,
        )


        self.assertIn(
            "5.41",
            all_ids,
        )


    def test_bc_e_advanced_audit_inventory_has_27_unique_guids(
        self,
    ) -> None:

        data = load_yaml_file(
            VARS_ROOT
            / "advanced_audit.yml"
        )


        policies = data[
            "crucible_cis_windows_10_advanced_audit_policies"
        ]


        self.assertEqual(
            len(
                policies
            ),
            27,
        )


        ids = {

            policy[
                "control_id"
            ]

            for policy
            in policies
        }


        guids = {

            policy[
                "guid"
            ].lower()

            for policy
            in policies
        }


        self.assertEqual(
            len(ids),
            27,
        )


        self.assertEqual(
            len(guids),
            27,
        )


    # ========================================================
    # BC-F
    # ========================================================

    def test_bc_f_has_8_event_log_controls(
        self,
    ) -> None:

        self.assertEqual(
            len(
                BC_F_EVENT_LOG_IDS
            ),
            8,
        )


        for control_id in (
            BC_F_EVENT_LOG_IDS
        ):

            control = (
                self.controls_by_id[
                    control_id
                ]
            )


            self.assertEqual(
                control.crucible_implementation,
                "automated",
            )


            self.assertIn(
                "area:event-logs",
                control.tags,
            )


    def test_bc_f_has_19_level1_defender_controls(
        self,
    ) -> None:

        self.assertEqual(
            len(
                BC_F_DEFENDER_LEVEL1_IDS
            ),
            19,
        )


        for control_id in (
            BC_F_DEFENDER_LEVEL1_IDS
        ):

            self.assertEqual(
                self.controls_by_id[
                    control_id
                ].crucible_implementation,
                "automated",
            )


    def test_bc_f_level2_defender_controls_are_now_complete(
        self,
    ) -> None:

        for control_id in (
            BC_F_DEFENDER_LEVEL2_IDS
        ):

            self.assertEqual(
                self.controls_by_id[
                    control_id
                ].crucible_implementation,
                "automated",
            )


    def test_bc_f_event_log_inventory_has_8_entries(
        self,
    ) -> None:

        data = load_yaml_file(
            VARS_ROOT
            / "event_logs.yml"
        )


        policies = data[
            "crucible_cis_windows_10_event_log_registry_policies"
        ]


        self.assertEqual(
            len(
                policies
            ),
            8,
        )


        self.assertEqual(
            {
                policy[
                    "control_id"
                ]
                for policy
                in policies
            },
            BC_F_EVENT_LOG_IDS,
        )


    def test_bc_f_defender_inventory_has_18_primary_policies(
        self,
    ) -> None:

        data = load_yaml_file(
            VARS_ROOT
            / "defender.yml"
        )


        policies = data[
            "crucible_cis_windows_10_defender_registry_policies"
        ]


        self.assertEqual(
            len(
                policies
            ),
            18,
        )


    def test_bc_f_defender_has_13_unique_asr_rules(
        self,
    ) -> None:

        data = load_yaml_file(
            VARS_ROOT
            / "defender.yml"
        )


        rules = data[
            "crucible_cis_windows_10_defender_asr_rules"
        ]


        self.assertEqual(
            len(
                rules
            ),
            13,
        )


        self.assertEqual(
            len(
                {
                    rule.lower()
                    for rule
                    in rules
                }
            ),
            13,
        )


    # ========================================================
    # BC-G
    # ========================================================

    def test_bc_g_generated_policy_inventory_covers_216_controls(
        self,
    ) -> None:

        data = load_yaml_file(
            VARS_ROOT
            / "administrative_templates.yml"
        )


        machine = data[
            "crucible_cis_windows_10_bc_g_machine_registry_policies"
        ]


        user = data[
            "crucible_cis_windows_10_bc_g_user_registry_policies"
        ]


        control_ids = {

            item[
                "control_id"
            ]

            for item
            in (
                machine
                +
                user
            )
        }


        self.assertEqual(
            len(
                control_ids
            ),
            216,
        )


    def test_bc_g_section_19_controls_are_user_registry_policies(
        self,
    ) -> None:

        data = load_yaml_file(
            VARS_ROOT
            / "administrative_templates.yml"
        )


        machine = data[
            "crucible_cis_windows_10_bc_g_machine_registry_policies"
        ]


        user = data[
            "crucible_cis_windows_10_bc_g_user_registry_policies"
        ]


        machine_section_19 = {

            item[
                "control_id"
            ]

            for item
            in machine

            if (
                item[
                    "control_id"
                ].startswith(
                    "19."
                )
            )
        }


        user_section_19 = {

            item[
                "control_id"
            ]

            for item
            in user

            if (
                item[
                    "control_id"
                ].startswith(
                    "19."
                )
            )
        }


        self.assertEqual(
            machine_section_19,
            set(),
        )


        self.assertGreater(
            len(
                user_section_19
            ),
            0,
        )


    def test_bc_g_user_registry_engine_targets_real_and_default_users(
        self,
    ) -> None:

        content = (
            TASK_ROOT
            / "user_registry_policy_engine.yml"
        ).read_text(
            encoding="utf-8",
        )


        self.assertIn(
            "ProfileList",
            content,
        )


        self.assertIn(
            "NTUSER.DAT",
            content,
        )


        self.assertIn(
            "Default User",
            content,
        )


        self.assertIn(
            "reg.exe",
            content,
        )


    # ========================================================
    # BC-H
    # ========================================================

    def test_bc_h_has_44_bitlocker_controls(
        self,
    ) -> None:

        controls = {

            control.id

            for control
            in self.controls

            if (
                "source-profile:bitlocker"
                in
                control.tags
            )
        }


        self.assertEqual(
            len(
                controls
            ),
            BC_H_BITLOCKER_COUNT,
        )


        for control_id in controls:

            control = (
                self.controls_by_id[
                    control_id
                ]
            )


            self.assertEqual(
                control.crucible_implementation,
                "automated",
            )


            self.assertIn(
                "wave:3",
                control.tags,
            )


            self.assertIn(
                "profile-addon:bitlocker",
                control.tags,
            )


    def test_bc_h_has_13_next_generation_controls(
        self,
    ) -> None:

        controls = {

            control.id

            for control
            in self.controls

            if (
                "source-profile:next-generation"
                in
                control.tags
            )
        }


        self.assertEqual(
            len(
                controls
            ),
            BC_H_NEXT_GENERATION_COUNT,
        )


        for control_id in controls:

            control = (
                self.controls_by_id[
                    control_id
                ]
            )


            self.assertEqual(
                control.crucible_implementation,
                "automated",
            )


            self.assertIn(
                "wave:3",
                control.tags,
            )


            self.assertIn(
                "profile-addon:next-generation",
                control.tags,
            )


            self.assertIn(
                "hardware-sensitive",
                control.tags,
            )


    def test_bc_h_generated_inventory_covers_57_controls(
        self,
    ) -> None:

        data = load_yaml_file(
            VARS_ROOT
            / "advanced_profiles.yml"
        )


        all_entries = (

            data[
                "crucible_cis_windows_10_"
                "bitlocker_machine_registry_policies"
            ]

            +

            data[
                "crucible_cis_windows_10_"
                "bitlocker_user_registry_policies"
            ]

            +

            data[
                "crucible_cis_windows_10_"
                "next_generation_machine_registry_policies"
            ]

            +

            data[
                "crucible_cis_windows_10_"
                "next_generation_user_registry_policies"
            ]
        )


        control_ids = {

            entry[
                "control_id"
            ]

            for entry
            in all_entries
        }


        self.assertEqual(
            len(
                control_ids
            ),
            BC_H_ADVANCED_COUNT,
        )


        bitlocker_ids = {

            control_id

            for control_id
            in control_ids

            if (
                "source-profile:bitlocker"
                in
                self.controls_by_id[
                    control_id
                ].tags
            )
        }


        next_generation_ids = {

            control_id

            for control_id
            in control_ids

            if (
                "source-profile:next-generation"
                in
                self.controls_by_id[
                    control_id
                ].tags
            )
        }


        self.assertEqual(
            len(
                bitlocker_ids
            ),
            44,
        )


        self.assertEqual(
            len(
                next_generation_ids
            ),
            13,
        )


    # ========================================================
    # PDF parser regression tests accumulated during BC-G/H
    # ========================================================

    def test_parser_accepts_long_machine_hive(
        self,
    ) -> None:

        self.assertEqual(

            parse_location(
                (
                    "HKEY_LOCAL_MACHINE\\"
                    "SOFTWARE\\Policies\\Microsoft\\Windows\\"
                    "PreviewBuilds:AllowBuildPreview"
                )
            ),

            (
                "HKLM",

                (
                    "SOFTWARE\\Policies\\Microsoft\\Windows\\"
                    "PreviewBuilds"
                ),

                "AllowBuildPreview",
            ),
        )


    def test_parser_accepts_long_current_user_hive(
        self,
    ) -> None:

        self.assertEqual(

            parse_location(
                (
                    "HKEY_CURRENT_USER\\"
                    "SOFTWARE\\Policies\\Example:"
                    "ExampleValue"
                )
            ),

            (
                "HKCU",

                "SOFTWARE\\Policies\\Example",

                "ExampleValue",
            ),
        )


    def test_parser_accepts_cis_user_sid_placeholder(
        self,
    ) -> None:

        self.assertEqual(

            parse_location(
                (
                    "HKU\\[USER SID]\\"
                    "Software\\Microsoft\\Windows\\"
                    "CurrentVersion\\Policies\\Attachments:"
                    "SaveZoneInformation"
                )
            ),

            (
                "HKCU",

                (
                    "Software\\Microsoft\\Windows\\"
                    "CurrentVersion\\Policies\\Attachments"
                ),

                "SaveZoneInformation",
            ),
        )


    def test_parser_accepts_joined_user_sid_placeholder(
        self,
    ) -> None:

        self.assertEqual(

            parse_location(
                (
                    "HKU\\[USERSID]\\"
                    "Software\\Policies\\Microsoft\\Windows\\"
                    "CloudContent:"
                    "DisableWindowsSpotlightFeatures"
                )
            ),

            (
                "HKCU",

                (
                    "Software\\Policies\\Microsoft\\Windows\\"
                    "CloudContent"
                ),

                "DisableWindowsSpotlightFeatures",
            ),
        )


    def test_parser_rejects_specific_hku_sid(
        self,
    ) -> None:

        with self.assertRaises(
            ValueError
        ):

            parse_location(
                (
                    "HKU\\"
                    "S-1-5-21-111-222-333-1001\\"
                    "Software\\Policies\\Example:"
                    "ExampleValue"
                )
            )


    def test_parser_reassembles_wrapped_value_name(
        self,
    ) -> None:

        audit_text = (
            "This group policy setting is backed by the "
            "following registry location with a "
            "REG_DWORD value of 2.\n"
            "HKU\\[USER\n"
            "SID]\\Software\\Microsoft\\Windows\\CurrentVersion\\"
            "Policies\\Attachments:SaveZoneI\n"
            "nformationPage 1228\n"
        )


        locations = (
            extract_registry_locations(
                audit_text
            )
        )


        self.assertEqual(
            len(
                locations
            ),
            1,
        )


        self.assertEqual(
            locations[0][1],
            (
                "HKU\\[USERSID]\\"
                "Software\\Microsoft\\Windows\\CurrentVersion\\"
                "Policies\\Attachments:"
                "SaveZoneInformation"
            ),
        )


    def test_allow_build_preview_has_explicit_override(
        self,
    ) -> None:

        entries = (
            REGISTRY_POLICY_OVERRIDES[
                "18.10.16.8"
            ]
        )


        self.assertEqual(
            len(
                entries
            ),
            1,
        )


        entry = entries[0]


        self.assertEqual(
            entry["name"],
            "AllowBuildPreview",
        )


        self.assertEqual(
            entry["type"],
            "dword",
        )


        self.assertEqual(
            entry["data"],
            0,
        )


    def test_blank_reg_sz_descriptor_is_supported(
        self,
    ) -> None:

        lines = [

            (
                "This group policy setting is backed by "
                "the following registry location with a "
                "REG_SZ that is <blank> i.e. no value set."
            ),

            (
                "HKLM\\SOFTWARE\\Policies\\Microsoft\\FVE:"
                "FDVDiscoveryVolumeType"
            ),
        ]


        registry_type, value_text = (
            descriptor_for_location(
                lines,
                1,
            )
        )


        self.assertEqual(
            registry_type,
            "SZ",
        )


        self.assertIn(
            "blank",
            value_text.lower(),
        )


    def test_bitlocker_blank_reg_sz_control_parses(
        self,
    ) -> None:

        block = """
18.10.10.1.1 (BL) Example

Profile Applicability:
- BitLocker

Audit:
Navigate to the UI Path articulated in the Remediation
section and confirm it is set as prescribed. This group
policy setting is backed by the following registry
location with a REG_SZ that is <blank> i.e. no value set.
HKLM\\SOFTWARE\\Policies\\Microsoft\\FVE:FDVDiscoveryVolumeType

Remediation:
Set the policy to Disabled.
"""


        entries = (
            registry_entries_for_control(
                "18.10.10.1.1",
                block,
            )
        )


        self.assertEqual(
            len(
                entries
            ),
            1,
        )


        entry = entries[0]


        self.assertEqual(
            entry["path"],
            (
                "HKLM:\\"
                "SOFTWARE\\Policies\\Microsoft\\FVE"
            ),
        )


        self.assertEqual(
            entry["name"],
            "FDVDiscoveryVolumeType",
        )


        self.assertEqual(
            entry["type"],
            "string",
        )


        self.assertEqual(
            entry["data"],
            "",
        )


    # ========================================================
    # High-numbered control ID regression
    # ========================================================

    def test_high_number_control_ids_survive_pdf_import(
        self,
    ) -> None:

        expected = {

            "18.10.10.1.10",

            "18.10.10.2.10",

            "18.10.10.2.11",

            "18.10.10.3.10",

            "18.10.10.3.11",

            "18.10.10.3.12",

            "18.10.57.3.10.1",

            "18.10.57.3.10.2",

            "18.10.57.3.11.1",
        }


        self.assertTrue(
            expected.issubset(
                self.controls_by_id
            )
        )


    # ========================================================
    # Role structure
    # ========================================================

    def test_complete_windows_role_structure_exists(
        self,
    ) -> None:

        expected_tasks = {

            "main.yml",

            "preflight.yml",

            "account_policies.yml",

            "user_rights.yml",

            "security_options.yml",

            "services.yml",

            "firewall.yml",

            "advanced_audit.yml",

            "event_logs.yml",

            "defender.yml",

            "administrative_templates.yml",

            "bitlocker.yml",

            "next_generation.yml",

            "registry_policy_engine.yml",

            "user_registry_policy_engine.yml",

            "verify.yml",

            "final_validation.yml",

            "completion.yml",
        }


        for filename in (
            expected_tasks
        ):

            with self.subTest(
                task=filename
            ):

                self.assertTrue(
                    (
                        TASK_ROOT
                        /
                        filename
                    ).is_file()
                )


    def test_main_role_orders_final_validation_before_completion(
        self,
    ) -> None:

        content = (
            TASK_ROOT
            / "main.yml"
        ).read_text(
            encoding="utf-8",
        )


        verify_position = (
            content.index(
                "file: verify.yml"
            )
        )


        final_position = (
            content.index(
                "file: final_validation.yml"
            )
        )


        completion_position = (
            content.index(
                "file: completion.yml"
            )
        )


        self.assertLess(
            verify_position,
            final_position,
        )


        self.assertLess(
            final_position,
            completion_position,
        )


    def test_account_policy_engine_uses_windows_security_policy(
        self,
    ) -> None:

        content = (
            TASK_ROOT
            / "account_policies.yml"
        ).read_text(
            encoding="utf-8",
        )


        self.assertIn(
            "community.windows.win_security_policy",
            content,
        )


        self.assertIn(
            "ansible.windows.win_regedit",
            content,
        )


    def test_user_right_engine_uses_win_user_right(
        self,
    ) -> None:

        content = (
            TASK_ROOT
            / "user_rights.yml"
        ).read_text(
            encoding="utf-8",
        )


        self.assertIn(
            "ansible.windows.win_user_right",
            content,
        )


        self.assertIn(
            "SeNetworkLogonRight",
            content,
        )


        self.assertIn(
            "SeServiceLogonRight",
            content,
        )


    def test_registry_policy_engine_marks_reboot_required_on_change(
        self,
    ) -> None:

        content = (
            TASK_ROOT
            / "registry_policy_engine.yml"
        ).read_text(
            encoding="utf-8",
        )


        self.assertIn(
            "ansible.windows.win_regedit",
            content,
        )


        self.assertIn(
            "crucible_cis_windows_10_reboot_required",
            content,
        )


    def test_firewall_preserves_crucible_winrm_rule(
        self,
    ) -> None:

        content = (
            TASK_ROOT
            / "firewall.yml"
        ).read_text(
            encoding="utf-8",
        )


        self.assertIn(
            "Crucible-WinRM-HTTPS",
            content,
        )


        self.assertIn(
            "5986",
            content,
        )


        self.assertIn(
            "ansible.windows.win_ping",
            content,
        )


    # ========================================================
    # BC-I finalization structure
    # ========================================================

    def test_bc_i_final_validation_reboots_and_reconnects(
        self,
    ) -> None:

        content = (
            TASK_ROOT
            / "final_validation.yml"
        ).read_text(
            encoding="utf-8",
        )


        self.assertIn(
            "ansible.windows.win_reboot",
            content,
        )


        self.assertIn(
            "ansible.windows.win_ping",
            content,
        )


        self.assertIn(
            "5986",
            content,
        )


        self.assertIn(
            "file: verify.yml",
            content,
        )


    def test_bc_i_final_validation_uses_fingerprint(
        self,
    ) -> None:

        content = (
            TASK_ROOT
            / "final_validation.yml"
        ).read_text(
            encoding="utf-8",
        )


        self.assertIn(
            "finalization_fingerprint",
            content,
        )


        self.assertIn(
            "sha256",
            content,
        )


        self.assertIn(
            "previous_final_state",
            content,
        )


    def test_bc_i_writes_final_evidence(
        self,
    ) -> None:

        content = (
            TASK_ROOT
            / "final_validation.yml"
        ).read_text(
            encoding="utf-8",
        )


        self.assertIn(
            "windows-10-cis-evidence.json",
            (
                ROLE_ROOT
                / "defaults"
                / "main.yml"
            ).read_text(
                encoding="utf-8",
            ),
        )


        self.assertIn(
            "implementation-validation-passed",
            content,
        )


        self.assertIn(
            "benchmark_accounting",
            content,
        )


        self.assertIn(
            "not-attested",
            content,
        )


    def test_bc_i_completion_marker_is_final(
        self,
    ) -> None:

        content = (
            TASK_ROOT
            / "completion.yml"
        ).read_text(
            encoding="utf-8",
        )


        self.assertIn(
            "'BC-I'",
            content,
        )


        self.assertIn(
            "'implementation-validation-passed'",
            content,
        )


        self.assertIn(
            "'not-attested'",
            content,
        )


        self.assertIn(
            "'not_implemented_controls'",
            content,
        )


    def test_bc_i_completion_requires_final_validation(
        self,
    ) -> None:

        content = (
            TASK_ROOT
            / "completion.yml"
        ).read_text(
            encoding="utf-8",
        )


        self.assertIn(
            "crucible_cis_windows_10_final_validation_passed",
            content,
        )


        self.assertIn(
            "ansible.builtin.assert",
            content,
        )


    # ========================================================
    # Final implementation-state sanity
    # ========================================================

    def test_maximum_profile_accounts_for_all_494_controls(
        self,
    ) -> None:

        plan = (
            build_hardening_plan(
                self.catalog,

                benchmark_id=(
                    BENCHMARK_ID
                ),

                machine_profile_id=(
                    "windows-10"
                ),

                requested_profile=(
                    "level2-bitlocker-next-generation"
                ),

                capabilities=[
                    "management:winrm",
                ],
            )
        )


        self.assertEqual(
            len(
                plan.applicable_controls
            ),
            494,
        )


        self.assertEqual(
            set(
                plan.not_implemented_control_ids
            ),
            set(),
        )


        for control_id in (
            MANAGEMENT_SENSITIVE_CONTROL_IDS
        ):

            self.assertIn(
                control_id,
                plan.derived_exception_control_ids,
            )


        self.assertEqual(
            set(
                plan.manual_control_ids
            ),
            MANUAL_CONTROL_IDS,
        )


        self.assertEqual(
            set(
                plan.audit_only_control_ids
            ),
            AUDIT_ONLY_CONTROL_IDS,
        )


if __name__ == "__main__":

    unittest.main()