import unittest
from pathlib import Path

from crucible.configurations.catalog import (
    ConfigurationCatalogError,
    combine_network_requirements,
    compatible_configurations,
    load_configuration_catalog,
    resolve_configuration_ids,
    validate_manifest_configurations,
    validate_topology_requirements,
)
from crucible.configurations.catalog import (
    build_configuration_execution_plan,
    resolve_configuration_parameters,
)


REPO_ROOT = (
    Path(__file__)
    .resolve()
    .parents[1]
)

CATALOG_PATH = (
    REPO_ROOT
    / "config"
    / "configurations.yml"
)


UBUNTU_SERVER_PROFILE = {
    "id": "ubuntu-26.04-server",

    "os": {
        "family": "linux",
        "distribution": "ubuntu",
        "version": "26.04",
        "flavor": "server",
        "architecture": "amd64",
    },
}


UBUNTU_DESKTOP_PROFILE = {
    "id": "ubuntu-26.04-desktop",

    "os": {
        "family": "linux",
        "distribution": "ubuntu",
        "version": "26.04",
        "flavor": "desktop",
        "architecture": "amd64",
    },
}


KALI_PROFILE = {
    "id": "kali-rolling",

    "os": {
        "family": "linux",
        "distribution": "kali",
        "version": "rolling",
        "flavor": "installer",
        "architecture": "amd64",
    },
}


WINDOWS_10_PROFILE = {
    "id": "windows-10",

    "os": {
        "family": "windows",
        "distribution": "windows",
        "version": "10",
        "architecture": "amd64",
    },
}


WINDOWS_SERVER_PROFILE = {
    "id": "windows-server-2022",

    "os": {
        "family": "windows",
        "distribution": "windows-server",
        "version": "2022",
        "architecture": "amd64",
    },
}


class ConfigurationCatalogTests(
    unittest.TestCase
):

    @classmethod
    def setUpClass(
        cls,
    ):
        cls.catalog = (
            load_configuration_catalog(
                CATALOG_PATH
            )
        )


    def test_catalog_loads(
        self,
    ):
        self.assertEqual(
            self.catalog.schema_version,
            1,
        )

        self.assertIn(
            "nftables",
            self.catalog.definitions,
        )

        self.assertIn(
            "ubuntu-cis",
            self.catalog.definitions,
        )

        self.assertIn(
            "active-directory-domain-controller",
            self.catalog.definitions,
        )


    def test_ubuntu_server_selectable_configuration(
        self,
    ):
        configurations = (
            compatible_configurations(
                self.catalog,
                UBUNTU_SERVER_PROFILE,
            )
        )

        ids = {
            configuration.id
            for configuration
            in configurations
        }

        self.assertEqual(
            ids,
            {
                "nftables",
                "ubuntu-cis"
            },
        )


    def test_ubuntu_server_planned_configurations(
        self,
    ):
        configurations = (
            compatible_configurations(
                self.catalog,
                UBUNTU_SERVER_PROFILE,
                selectable_only=False,
            )
        )

        ids = {
            configuration.id
            for configuration
            in configurations
        }

        self.assertIn(
            "nftables",
            ids,
        )

        self.assertIn(
            "ubuntu-cis",
            ids,
        )

        self.assertIn(
            "authoritative-dns",
            ids,
        )

        self.assertIn(
            "dhcp-server",
            ids,
        )


    def test_ubuntu_desktop_matches_future_ubuntu_cis(
        self,
    ):
        configurations = (
            compatible_configurations(
                self.catalog,
                UBUNTU_DESKTOP_PROFILE,
                selectable_only=False,
            )
        )

        ids = {
            configuration.id
            for configuration
            in configurations
        }

        self.assertIn(
            "nftables",
            ids,
        )

        self.assertIn(
            "ubuntu-cis",
            ids,
        )


    def test_kali_matches_nftables(
        self,
    ):
        configurations = (
            compatible_configurations(
                self.catalog,
                KALI_PROFILE,
            )
        )

        ids = {
            configuration.id
            for configuration
            in configurations
        }

        self.assertIn(
            "nftables",
            ids,
        )


    def test_windows_10_has_no_current_configuration(
        self,
    ):
        configurations = (
            compatible_configurations(
                self.catalog,
                WINDOWS_10_PROFILE,
                selectable_only=False,
            )
        )

        self.assertEqual(
            configurations,
            [],
        )


    def test_windows_server_matches_future_services(
        self,
    ):
        configurations = (
            compatible_configurations(
                self.catalog,
                WINDOWS_SERVER_PROFILE,
                selectable_only=False,
            )
        )

        ids = {
            configuration.id
            for configuration
            in configurations
        }

        self.assertIn(
            "active-directory-domain-controller",
            ids,
        )

        self.assertIn(
            "authoritative-dns",
            ids,
        )

        self.assertIn(
            "dhcp-server",
            ids,
        )


    def test_unknown_configuration_rejected(
        self,
    ):
        with self.assertRaises(
            ConfigurationCatalogError
        ):
            resolve_configuration_ids(
                [
                    "does-not-exist",
                ],
                self.catalog,
                UBUNTU_SERVER_PROFILE,
            )


    def test_incompatible_configuration_rejected(
        self,
    ):
        with self.assertRaises(
            ConfigurationCatalogError
        ):
            resolve_configuration_ids(
                [
                    "nftables",
                ],
                self.catalog,
                WINDOWS_10_PROFILE,
            )


    def test_duplicate_configuration_rejected(
        self,
    ):
        with self.assertRaises(
            ConfigurationCatalogError
        ):
            resolve_configuration_ids(
                [
                    "nftables",
                    "nftables",
                ],
                self.catalog,
                UBUNTU_SERVER_PROFILE,
            )


    def test_static_internal_requirement_passes(
        self,
    ):
        definition = (
            self.catalog.get(
                "active-directory-domain-controller"
            )
        )

        topology = [
            {
                "label": "lan",

                "attachment": {
                    "type": "intnet",
                    "network": "LAB-LAN",
                },

                "ipv4": {
                    "method": "static",
                    "address": "192.168.50.10/24",
                    "gateway": None,
                },
            }
        ]

        validate_topology_requirements(
            topology,
            definition.network_requirements,
        )


    def test_dhcp_internal_does_not_satisfy_static_requirement(
        self,
    ):
        definition = (
            self.catalog.get(
                "active-directory-domain-controller"
            )
        )

        topology = [
            {
                "label": "lan",

                "attachment": {
                    "type": "intnet",
                    "network": "LAB-LAN",
                },

                "ipv4": {
                    "method": "dhcp",
                    "address": None,
                    "gateway": None,
                },
            }
        ]

        with self.assertRaises(
            ConfigurationCatalogError
        ):
            validate_topology_requirements(
                topology,
                definition.network_requirements,
            )


    def test_bridged_static_does_not_satisfy_static_internal(
        self,
    ):
        definition = (
            self.catalog.get(
                "dhcp-server"
            )
        )

        topology = [
            {
                "label": "lan",

                "attachment": {
                    "type": "bridged",
                    "adapter": "eth0",
                },

                "ipv4": {
                    "method": "static",
                    "address": "192.168.1.50/24",
                    "gateway": "192.168.1.1",
                },
            }
        ]

        with self.assertRaises(
            ConfigurationCatalogError
        ):
            validate_topology_requirements(
                topology,
                definition.network_requirements,
            )


    def test_nftables_manifest_is_valid(
        self,
    ):
        manifest = {
            "configurations": [
                {
                    "id": "nftables",
                    "parameters": {},
                }
            ],

            "network": {
                "topology": [],
            },
        }

        definitions = (
            validate_manifest_configurations(
                manifest,
                UBUNTU_SERVER_PROFILE,
                self.catalog,
            )
        )

        self.assertEqual(
            len(
                definitions
            ),
            1,
        )

        self.assertEqual(
            definitions[0].id,
            "nftables",
        )


    def test_manifest_parameters_must_be_mapping(
        self,
    ):
        manifest = {
            "configurations": [
                {
                    "id": "nftables",
                    "parameters": "wrong",
                }
            ],

            "network": {
                "topology": [],
            },
        }

        with self.assertRaises(
            ConfigurationCatalogError
        ):
            validate_manifest_configurations(
                manifest,
                UBUNTU_SERVER_PROFILE,
                self.catalog,
            )

    def test_nftables_supports_all_linux(
        self,
    ):
        generic_linux_profile = {
            "id": "future-linux",

            "os": {
                "family": "linux",
                "distribution": "future-linux",
                "version": "1",
                "architecture": "amd64",
            },
        }

        configurations = (
            compatible_configurations(
                self.catalog,
                generic_linux_profile,
            )
        )

        ids = {
            definition.id

            for definition
            in configurations
        }

        self.assertIn(
            "nftables",
            ids,
        )


    def test_nftables_execution_order(
        self,
    ):
        definition = (
            self.catalog.get(
                "nftables"
            )
        )

        plan = (
            build_configuration_execution_plan(
                (
                    definition,
                )
            )
        )

        self.assertEqual(
            plan[
                0
            ].id,
            "nftables",
        )

        self.assertEqual(
            plan[
                0
            ].implementation[
                "order"
            ],
            900,
        )


    def test_nftables_parameter_override(
        self,
    ):
        definition = (
            self.catalog.get(
                "nftables"
            )
        )

        parameters = (
            resolve_configuration_parameters(
                definition,
                {
                    "allow_topology_ssh": True,
                    "log_rate": "10/second",
                },
            )
        )

        self.assertTrue(
            parameters[
                "allow_topology_ssh"
            ]
        )

        self.assertEqual(
            parameters[
                "log_rate"
            ],
            "10/second",
        )


    def test_unknown_parameter_rejected(
        self,
    ):
        definition = (
            self.catalog.get(
                "nftables"
            )
        )

        with self.assertRaises(
            ConfigurationCatalogError
        ):
            resolve_configuration_parameters(
                definition,
                {
                    "totally_fake_option": True,
                },
            )

    def test_ubuntu_cis_references_hardening_benchmark(
        self,
    ):
        definition = (
            self.catalog.get(
                "ubuntu-cis"
            )
        )

        self.assertIsNotNone(
            definition.hardening
        )

        self.assertEqual(
            definition.hardening[
                "benchmark"
            ],
            "cis-ubuntu-linux-26.04",
        )

        self.assertEqual(
            definition.hardening[
                "profile_parameter"
            ],
            "profile",
        )

        self.assertEqual(
            definition.hardening[
                "exceptions_parameter"
            ],
            "exceptions",
        )


if __name__ == "__main__":
    unittest.main()