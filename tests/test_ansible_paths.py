from pathlib import Path
import re
import unittest


REPO_ROOT = (
    Path(__file__)
    .resolve()
    .parents[1]
)


ROLE_ROOT = (
    REPO_ROOT
    / "ansible"
    / "roles"
    / "crucible_cis_ubuntu_26_04"
)


BAD_FOLDED_PATH = re.compile(
    r"""
    ^[ \t]*
    (?:path|dest|src):
    [ \t]*>-
    [ \t]*\n
    [ \t]+[^\n]*/[ \t]*\n
    [ \t]+\S
    """,
    re.MULTILINE
    | re.VERBOSE,
)


class AnsiblePathTests(
    unittest.TestCase
):

    def test_paths_are_not_joined_with_folded_yaml(
        self,
    ) -> None:

        failures: list[str] = []

        for path in ROLE_ROOT.rglob(
            "*.yml"
        ):

            text = path.read_text(
                encoding="utf-8"
            )

            if BAD_FOLDED_PATH.search(
                text
            ):

                failures.append(
                    str(
                        path.relative_to(
                            REPO_ROOT
                        )
                    )
                )

        self.assertEqual(
            failures,
            [],
            (
                "Folded YAML scalars must not "
                "be used to concatenate "
                "filesystem path components:\n"
                +
                "\n".join(
                    failures
                )
            ),
        )


if __name__ == "__main__":
    unittest.main()