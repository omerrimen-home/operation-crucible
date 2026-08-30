import unittest

from crucible.networking.layout import (
    build_network_slot_layout,
    legacy_linux_interface_for_slot,
)


class NetworkLayoutTests(
    unittest.TestCase
):
    def test_no_internal_networks(self):
        layout = (
            build_network_slot_layout(
                0
            )
        )

        self.assertEqual(
            layout.topology_slots,
            (),
        )

        self.assertEqual(
            layout.internet_slot,
            1,
        )

        self.assertEqual(
            layout.management_slot,
            2,
        )

    def test_one_internal_network(self):
        layout = (
            build_network_slot_layout(
                1
            )
        )

        self.assertEqual(
            layout.topology_slots,
            (1,),
        )

        self.assertEqual(
            layout.internet_slot,
            2,
        )

        self.assertEqual(
            layout.management_slot,
            3,
        )

    def test_two_internal_networks(self):
        layout = (
            build_network_slot_layout(
                2
            )
        )

        self.assertEqual(
            layout.topology_slots,
            (1, 2),
        )

        self.assertEqual(
            layout.internet_slot,
            3,
        )

        self.assertEqual(
            layout.management_slot,
            4,
        )

    def test_maximum_internal_networks(self):
        layout = (
            build_network_slot_layout(
                6
            )
        )

        self.assertEqual(
            layout.topology_slots,
            (1, 2, 3, 4, 5, 6),
        )

        self.assertEqual(
            layout.internet_slot,
            7,
        )

        self.assertEqual(
            layout.management_slot,
            8,
        )

    def test_too_many_networks(self):
        with self.assertRaises(
            ValueError
        ):
            build_network_slot_layout(
                7
            )

    def test_legacy_linux_names(self):
        self.assertEqual(
            legacy_linux_interface_for_slot(
                1
            ),
            "eth0",
        )

        self.assertEqual(
            legacy_linux_interface_for_slot(
                2
            ),
            "eth1",
        )

        self.assertEqual(
            legacy_linux_interface_for_slot(
                4
            ),
            "eth3",
        )


if __name__ == "__main__":
    unittest.main()