import unittest

from crucible.configurations.catalog import (
    ConfigurationDefinition,
    NetworkRequirements,
)

from crucible.configurations.runtime import (
    build_configuration_runtime_context,
)


class ConfigurationRuntimeTests(
    unittest.TestCase
):

    def test_firewall_contracts_are_aggregated(
        self,
    ):
        nftables = ConfigurationDefinition(
            id="nftables",
            display_name="nftables",
            description="Firewall",
            selectable=True,
            supported_os=(
                {
                    "family": "linux",
                },
            ),
            network_requirements=(
                NetworkRequirements()
            ),
            implementation={
                "backend": "ansible",
                "playbook": "fake.yml",
                "order": 900,
            },
            parameters={
                "input_policy": "drop",
            },
            relationships={
                "requires": (),
                "conflicts": (),
            },
            firewall={
                "inbound": [],
                "forward": [],
            },
        )

        dns = ConfigurationDefinition(
            id="dns",
            display_name="DNS",
            description="DNS",
            selectable=True,
            supported_os=(
                {
                    "family": "linux",
                },
            ),
            network_requirements=(
                NetworkRequirements()
            ),
            implementation={
                "backend": "ansible",
                "playbook": "dns.yml",
                "order": 300,
            },
            parameters={},
            relationships={
                "requires": (),
                "conflicts": (),
            },
            firewall={
                "inbound": [
                    {
                        "id": "dns-udp",
                        "direction": "inbound",
                        "protocol": "udp",
                        "ports": [
                            53,
                        ],
                        "source_ports": [],
                        "source_scope": "topology",
                        "destination_scope": None,
                        "source_addresses": [],
                        "comment": "DNS",
                    }
                ],
                "forward": [],
            },
            capabilities=(
                "service:dns-server",
            ),
        )

        manifest = {
            "name": "test",
            "profile": "test-linux",

            "instance": {
                "serial": "CRU-TEST",
            },

            "network": {
                "topology": [],
                "internet": {
                    "enabled": True,
                },
                "management": {},
            },

            "configurations": [
                {
                    "id": "nftables",
                    "parameters": {},
                },
                {
                    "id": "dns",
                    "parameters": {},
                },
            ],
        }

        context = (
            build_configuration_runtime_context(
                manifest,
                (
                    nftables,
                    dns,
                ),
                current_configuration_id=(
                    "nftables"
                ),
            )
        )

        self.assertIn(
            "service:dns-server",
            context[
                "crucible_machine"
            ][
                "capabilities"
            ],
        )

        machine = (
            context[
                "crucible_machine"
            ]
        )

        self.assertEqual(
            machine[
                "name"
            ],
            "test",
        )

        self.assertEqual(
            machine[
                "profile"
            ],
            "test-linux",
        )

        self.assertEqual(
            machine[
                "instance_serial"
            ],
            "CRU-TEST",
        )

        self.assertEqual(
            machine[
                "network"
            ],
            manifest[
                "network"
            ],
        )

        self.assertIn(
            "management",
            machine[
                "network"
            ],
        )

        self.assertIn(
            "internet",
            machine[
                "network"
            ],
        )

        self.assertIn(
            "topology",
            machine[
                "network"
            ],
        )

        rules = (
            context[
                "crucible_firewall"
            ][
                "inbound"
            ]
        )

        self.assertEqual(
            len(
                rules
            ),
            1,
        )

        self.assertEqual(
            rules[
                0
            ][
                "ports"
            ],
            [
                53,
            ],
        )

        self.assertEqual(
            rules[
                0
            ][
                "owner_configuration"
            ],
            "dns",
        )


if __name__ == "__main__":
    unittest.main()