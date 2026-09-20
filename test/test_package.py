try:
    from importlib.metadata import distribution
except ImportError:  # pragma: no cover - Python 3.7 compatibility
    from importlib_metadata import distribution

from pathlib import Path


def test_distribution_metadata_and_plugin_entry_point():
    package = distribution("OctoPrint-RepeatingCommand")

    assert package.version == "0.1.0"
    entry_points = [
        entry_point
        for entry_point in package.entry_points
        if entry_point.group == "octoprint.plugin"
    ]
    assert [(entry_point.name, entry_point.value) for entry_point in entry_points] == [
        ("repeatingcommand", "octoprint_repeatingcommand")
    ]


def test_distribution_contains_plugin_assets():
    project_root = Path(__file__).resolve().parents[1]

    assert (project_root / "octoprint_repeatingcommand/__init__.py").is_file()
    assert (project_root / "octoprint_repeatingcommand/static/js/repeatingcommand.js").is_file()
    assert (
        project_root
        / "octoprint_repeatingcommand/templates/repeatingcommand_settings.jinja2"
    ).is_file()
