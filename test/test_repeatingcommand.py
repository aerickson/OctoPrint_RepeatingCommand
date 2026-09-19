import importlib
import sys
import types

import pytest


class FakeTimer:
    instances = []

    def __init__(self, interval, callback, run_first=False):
        self.interval = interval
        self.callback = callback
        self.run_first = run_first
        self.started = False
        self.cancelled = False
        self.__class__.instances.append(self)

    def start(self):
        self.started = True

    def cancel(self):
        self.cancelled = True


class FakeSettings:
    def __init__(self, values):
        self.values = values

    def get(self, path):
        value = self.values
        for key in path:
            value = value[key]
        return value


class FakeLogger:
    def __init__(self):
        self.info_messages = []
        self.warning_messages = []

    def info(self, message):
        self.info_messages.append(message)

    def warning(self, message):
        self.warning_messages.append(message)


def load_plugin():
    plugin_module = types.ModuleType("octoprint.plugin")
    plugin_module.EventHandlerPlugin = type("EventHandlerPlugin", (), {})
    plugin_module.SettingsPlugin = type("SettingsPlugin", (), {})
    plugin_module.AssetPlugin = type("AssetPlugin", (), {})
    plugin_module.TemplatePlugin = type("TemplatePlugin", (), {})

    util_module = types.ModuleType("octoprint.util")
    util_module.RepeatedTimer = FakeTimer

    octoprint_module = types.ModuleType("octoprint")
    octoprint_module.plugin = plugin_module
    octoprint_module.util = util_module

    sys.modules["octoprint"] = octoprint_module
    sys.modules["octoprint.plugin"] = plugin_module
    sys.modules["octoprint.util"] = util_module
    return importlib.import_module("octoprint_repeatingcommand")


@pytest.fixture(autouse=True)
def reset_fakes():
    FakeTimer.instances = []
    sys.modules.pop("octoprint_repeatingcommand", None)
    yield
    sys.modules.pop("octoprint_repeatingcommand", None)


def make_plugin(rules=None, **overrides):
    module = load_plugin()
    values = {
        "enabled": True,
        "command": "normal-command",
        "interval": 90,
        "cooling_command": "",
        "cooling_interval": 10,
        "cooling_message": "cooling",
        "cooling_states": "",
        "rules": rules or [],
        "verbose": False,
    }
    values.update(overrides)
    plugin = module.RepeatingCommandPlugin()
    plugin._settings = FakeSettings(values)
    plugin._logger = FakeLogger()
    plugin._plugin_name = "Repeating Command"
    plugin._plugin_version = "0.1.0"
    return plugin


def rule(command, interval=90, filtering_enabled=False, status_contains="", printer_states=""):
    return {
        "command": command,
        "interval": interval,
        "filtering_enabled": filtering_enabled,
        "status_contains": status_contains,
        "printer_states": printer_states,
    }


def test_filtered_rule_precedes_unfiltered_fallback():
    fallback = rule("normal")
    cooling = rule("cooling", 10, True, status_contains="cooling")
    plugin = make_plugin([fallback, cooling])
    plugin.current_status = "Layer finished - COOLING"
    plugin.print_active = True

    assert plugin._matching_rule() is cooling

    plugin.current_status = "Printing"
    assert plugin._matching_rule() is fallback


def test_rule_matches_multiple_statuses_and_states_case_insensitively():
    plugin = make_plugin()
    plugin.current_status = "Printer is cooling down"
    assert plugin._rule_matches(
        rule("fan", filtering_enabled=True, status_contains="paused, cooling")
    )

    plugin.current_status = "Printing"
    plugin.printer_state = "pAuSeD"
    assert plugin._rule_matches(
        rule("fan", filtering_enabled=True, printer_states="FINISHING, paused")
    )


def test_unfiltered_rule_is_not_used_after_print_done():
    plugin = make_plugin([rule("normal")])
    plugin.print_active = False

    assert plugin._desired_rule() is None


def test_print_lifecycle_starts_and_stops_timer():
    plugin = make_plugin([rule("normal", 90)])
    plugin.on_event("PrintStarted", {})

    timer = FakeTimer.instances[-1]
    assert timer.interval == 90
    assert timer.run_first is True
    assert timer.started is True

    plugin.on_event("PrintFailed", {})
    assert timer.cancelled is True
    assert plugin.timer is None


def test_m117_switches_to_filtered_rule_and_print_done_keeps_it_running():
    normal = rule("normal", 90)
    cooling = rule("cooling", 10, True, status_contains="cooling")
    plugin = make_plugin([normal, cooling])
    plugin.on_event("PrintStarted", {})
    normal_timer = FakeTimer.instances[-1]

    plugin.on_gcode_queuing(None, None, "M117 Cooling", None, "M117", None, None)
    cooling_timer = FakeTimer.instances[-1]
    assert normal_timer.cancelled is True
    assert cooling_timer.interval == 10
    assert plugin.current_status == "Cooling"

    plugin.on_event("PrintDone", {})
    assert plugin.timer is cooling_timer
    assert cooling_timer.cancelled is False

    plugin.on_gcode_queuing(None, None, "M117 Finished", None, "M117", None, None)
    assert plugin.timer is None
    assert cooling_timer.cancelled is True


def test_printer_state_switches_to_matching_rule():
    normal = rule("normal", 90)
    paused = rule("paused", 5, True, printer_states="PAUSED")
    plugin = make_plugin([normal, paused])
    plugin.on_event("PrintStarted", {})
    normal_timer = FakeTimer.instances[-1]

    plugin.on_event("PrinterStateChanged", {"state_id": "PAUSED"})
    paused_timer = FakeTimer.instances[-1]
    assert normal_timer.cancelled is True
    assert paused_timer.interval == 5


@pytest.mark.parametrize("interval", [0, -1, "not-a-number"])
def test_non_positive_or_invalid_interval_does_not_start_timer(interval):
    plugin = make_plugin([rule("invalid", interval)])
    plugin.on_event("PrintStarted", {})

    assert plugin.timer is None
    assert FakeTimer.instances == []
    assert plugin._logger.warning_messages


def test_legacy_settings_are_used_when_rules_are_empty():
    plugin = make_plugin(
        [],
        command="legacy-normal",
        interval=120,
        cooling_command="legacy-cooling",
        cooling_interval=10,
        cooling_message="cooling",
    )
    plugin.current_status = "cooling"

    assert plugin._matching_rule()["command"] == "legacy-cooling"
