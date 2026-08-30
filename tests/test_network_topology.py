import unittest

from crucible.networking.topology import (
    TopologyConfigurationError,
    build_dhcp_ipv4_configuration,
    build_static_ipv4_configuration,
    subnet_mask_to_prefix,
    topology_mac_for_machine,
)


class NetworkTopologyTests(
    unittest.TestCase
):

    def test_subnet_mask_conversion(self):
        self.assertEqual(
            subnet_mask_to_prefix(
                "255.255.255.0"
            ),
            24,
        )

        self.assertEqual(
            subnet_mask_to_prefix(
                "255.255.0.0"
            ),
            16,
        )

    def test_prefix_input(self):
        self.assertEqual(
            subnet_mask_to_prefix(
                "24"
            ),
            24,
        )

    def test_dhcp_configuration(self):
        config = (
            build_dhcp_ipv4_configuration()
        )

        self.assertEqual(
            config["method"],
            "dhcp",
        )

        self.assertIsNone(
            config["address"]
        )

        self.assertIsNone(
            config["gateway"]
        )

    def test_static_configuration(self):
        config = (
            build_static_ipv4_configuration(
                address="192.168.50.10",
                subnet_mask="255.255.255.0",
                gateway="192.168.50.1",
            )
        )

        self.assertEqual(
            config["method"],
            "static",
        )

        self.assertEqual(
            config["address"],
            "192.168.50.10/24",
        )

        self.assertEqual(
            config["gateway"],
            "192.168.50.1",
        )

    def test_static_without_gateway(self):
        config = (
            build_static_ipv4_configuration(
                address="10.10.10.5",
                subnet_mask="255.255.255.0",
                gateway=None,
            )
        )

        self.assertEqual(
            config["address"],
            "10.10.10.5/24",
        )

        self.assertIsNone(
            config["gateway"]
        )

    def test_gateway_outside_subnet(self):
        with self.assertRaises(
            TopologyConfigurationError
        ):
            build_static_ipv4_configuration(
                address="192.168.50.10",
                subnet_mask="255.255.255.0",
                gateway="192.168.60.1",
            )

    def test_mac_is_deterministic(self):
        first = topology_mac_for_machine(
            "ubuntu-01",
            1,
        )

        second = topology_mac_for_machine(
            "ubuntu-01",
            1,
        )

        self.assertEqual(
            first,
            second,
        )

    def test_different_slots_get_different_macs(self):
        first = topology_mac_for_machine(
            "ubuntu-01",
            1,
        )

        second = topology_mac_for_machine(
            "ubuntu-01",
            2,
        )

        self.assertNotEqual(
            first,
            second,
        )


if __name__ == "__main__":
    unittest.main()