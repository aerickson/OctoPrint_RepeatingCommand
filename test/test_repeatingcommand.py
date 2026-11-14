import importlib
import sys
import threading
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


class ImmediateThread:
    def __init__(self, target, args, **kwargs):
        self.target = target
        self.args = args

    def start(self):
        self.target(*self.args)


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
    module.Thread = ImmediateThread
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


def once_plugin(rules):
    plugin = make_plugin(rules)
    plugin.commands = []
    plugin.run_command = lambda command: (plugin.commands.append(command) or 0, b"ok")
    return plugin


def test_run_once_duplicate_events_and_reactivation():
    cooling = dict(rule("cool", filtering_enabled=True, status_contains="cooling"), run_once=True)
    plugin = once_plugin([cooling])
    for _ in range(2):
        plugin.on_gcode_queuing(None, None, "M117 Cooling", None, "M117", None, None)
        plugin.on_event("PrinterStateChanged", {"state_id": "OPERATIONAL"})
    assert plugin.commands == ["cool"]
    assert FakeTimer.instances == []
    plugin.on_gcode_queuing(None, None, "M117", None, "M117", None, None)
    plugin.on_gcode_queuing(None, None, "M117 Cooling", None, "M117", None, None)
    assert plugin.commands == ["cool", "cool"]


def test_run_once_print_lifecycle_and_cooling():
    normal = dict(rule("normal"), run_once=True)
    cooling = dict(rule("cool", filtering_enabled=True, status_contains="cooling"), run_once=True)
    plugin = once_plugin([normal, cooling])
    plugin.on_event("PrintStarted", {})
    plugin.on_event("PrintStarted", {})
    plugin.on_gcode_queuing(None, None, "M117 cooling", None, "M117", None, None)
    plugin.on_event("PrintDone", {})
    plugin.on_event("PrinterStateChanged", {"state_id": "OPERATIONAL"})
    assert plugin.commands == ["normal", "cool"]
    plugin.on_gcode_queuing(None, None, "M117", None, "M117", None, None)
    plugin.on_event("PrintStarted", {})
    assert plugin.commands == ["normal", "cool", "normal"]
    plugin.on_event("PrintFailed", {})
    plugin.on_event("PrintStarted", {})
    assert plugin.commands == ["normal", "cool", "normal", "normal"]


def test_run_once_precedence_does_not_reset_matching_rule():
    priority = rule("repeat", 5, True, printer_states="PAUSED")
    fallback = dict(rule("once"), run_once=True)
    plugin = once_plugin([fallback, priority])
    plugin.on_event("PrintStarted", {})
    plugin.on_event("PrinterStateChanged", {"state_id": "PAUSED"})
    timer = FakeTimer.instances[-1]
    assert timer.started
    plugin.on_event("PrinterStateChanged", {"state_id": "PRINTING"})
    assert timer.cancelled
    assert plugin.commands == ["once"]


def test_run_once_filtered_precedence_and_state_reactivation():
    selected = dict(rule("selected", filtering_enabled=True, printer_states="PAUSED"), run_once=True)
    plugin = once_plugin([rule("fallback"), selected])
    plugin.on_event("PrintStarted", {})
    normal_timer = FakeTimer.instances[-1]
    plugin.on_event("PrinterStateChanged", {"state_id": "PAUSED"})
    assert plugin.commands == ["selected"]
    assert normal_timer.cancelled
    plugin.on_event("PrinterStateChanged", {"state_id": "PRINTING"})
    timer = FakeTimer.instances[-1]
    plugin.on_event("PrinterStateChanged", {"state_id": "PAUSED"})
    assert timer.cancelled
    assert plugin.commands == ["selected", "selected"]


def test_disable_resets_run_once_activation():
    plugin = once_plugin([dict(rule("once", interval=0), run_once=True)])
    plugin.on_event("PrintStarted", {})
    plugin._settings.values["enabled"] = False
    plugin._refresh_timer()
    plugin._settings.values["enabled"] = True
    plugin._refresh_timer()
    assert plugin.commands == ["once", "once"]
    assert FakeTimer.instances == []


def test_reordering_rules_preserves_activation_history():
    once = dict(rule("once"), run_once=True)
    override = rule("override", filtering_enabled=True, printer_states="PAUSED")
    plugin = once_plugin([once, override])
    plugin.on_event("PrintStarted", {})
    plugin._settings.values["rules"] = [override, once]
    plugin.on_event("PrinterStateChanged", {"state_id": "PRINTING"})
    assert plugin.commands == ["once"]


class ImmediateTimer(FakeTimer):
    def start(self):
        super().start()
        if self.run_first:
            self.callback()


@pytest.mark.parametrize("run_once", [False, True])
@pytest.mark.parametrize("state_first", [False, True])
def test_print_transitions_never_launch_transient_fallback(monkeypatch, run_once, state_first):
    fallback = dict(rule("pulse-fan", 60), run_once=run_once)
    printing = rule("fan-on", 10, True, printer_states="PRINTING", status_contains="cooling")
    plugin = once_plugin([fallback, printing])
    monkeypatch.setattr(sys.modules["octoprint.util"], "RepeatedTimer", ImmediateTimer)
    plugin.printer_state = "OPERATIONAL"

    if state_first:
        plugin.on_event("PrinterStateChanged", {"state_id": "PRINTING"})
    plugin.on_event("PrintStarted", {})
    plugin.on_event("PrinterStateChanged", {"state_id": "PRINTING"})
    assert plugin.commands == ["fan-on"]

    plugin.on_gcode_queuing(None, None, "M117 Print Complete.", None, "M117", None, None)
    plugin.on_event("PrinterStateChanged", {"state_id": "FINISHING"})
    assert plugin.timer is None
    plugin.on_event("PrintDone", {})
    plugin.on_event("PrinterStateChanged", {"state_id": "OPERATIONAL"})
    # Even callbacks already queued by the old timer must do nothing.
    for timer in FakeTimer.instances:
        timer.callback()
    assert plugin.commands == ["fan-on"]
    assert all(timer.cancelled for timer in FakeTimer.instances)


def test_fallback_still_executes_immediately_for_normal_print(monkeypatch):
    plugin = once_plugin([rule("pulse-fan", 60)])
    monkeypatch.setattr(sys.modules["octoprint.util"], "RepeatedTimer", ImmediateTimer)
    plugin.on_event("PrintStarted", {})
    assert plugin.commands == ["pulse-fan"]
    plugin.on_event("PrinterStateChanged", {"state_id": "FINISHING"})
    plugin.on_event("PrintDone", {})
    assert plugin.commands == ["pulse-fan"]


def test_cancellation_does_not_restart_fallback(monkeypatch):
    plugin = once_plugin([rule("fallback"), rule("printing", 10, True, printer_states="PRINTING")])
    monkeypatch.setattr(sys.modules["octoprint.util"], "RepeatedTimer", ImmediateTimer)
    plugin.on_event("PrintStarted", {})
    plugin.on_event("PrinterStateChanged", {"state_id": "CANCELLING"})
    plugin.on_event("PrintCancelled", {})
    plugin.on_event("PrinterStateChanged", {"state_id": "OPERATIONAL"})
    assert plugin.commands == ["printing"]
    assert plugin.timer is None


@pytest.mark.parametrize("run_once", [False, True])
def test_finishing_preserves_explicit_cooling_rule(monkeypatch, run_once):
    cooling = dict(rule("cool", 10, True, status_contains="cooling"), run_once=run_once)
    plugin = once_plugin([rule("fallback"), cooling])
    monkeypatch.setattr(sys.modules["octoprint.util"], "RepeatedTimer", ImmediateTimer)
    plugin.on_event("PrintStarted", {})
    plugin.on_gcode_queuing(None, None, "M117 Cooling", None, "M117", None, None)
    cooling_timer = plugin.timer
    assert plugin.commands == ["fallback", "cool"]
    plugin.on_event("PrinterStateChanged", {"state_id": "FINISHING"})
    plugin.on_event("PrintDone", {})
    plugin.on_event("PrinterStateChanged", {"state_id": "OPERATIONAL"})
    assert plugin.commands == ["fallback", "cool"]
    assert plugin.timer is cooling_timer
    if cooling_timer:
        assert not cooling_timer.cancelled


def test_replaced_timer_cannot_execute_replacement_command():
    plugin = once_plugin([rule("normal"), rule("paused", 5, True, printer_states="PAUSED")])
    plugin.on_event("PrintStarted", {})
    old_timer = plugin.timer
    plugin.on_event("PrinterStateChanged", {"state_id": "PAUSED"})
    old_timer.callback()
    assert plugin.commands == []
    plugin.timer.callback()
    assert plugin.commands == ["paused"]
    plugin.stopTimer()
    old_timer.callback()
    assert plugin.commands == ["paused"]


def test_running_command_finishes_without_reusing_cancelled_timer():
    plugin = once_plugin([rule("normal"), rule("paused", 5, True, printer_states="PAUSED")])
    started = threading.Event()
    finish = threading.Event()

    def command(cmd):
        plugin.commands.append(cmd)
        started.set()
        assert finish.wait(timeout=5)
        return 0, b"ok"

    plugin.run_command = command
    plugin.on_event("PrintStarted", {})
    old_timer = plugin.timer
    worker = threading.Thread(target=old_timer.callback)
    worker.start()
    try:
        assert started.wait(timeout=5)
        plugin.on_event("PrinterStateChanged", {"state_id": "PAUSED"})
        assert old_timer.cancelled
        old_timer.callback()
        assert plugin.commands == ["normal"]
    finally:
        finish.set()
        worker.join(timeout=5)
    assert not worker.is_alive()
    plugin.timer.callback()
    assert plugin.commands == ["normal", "paused"]


@pytest.mark.parametrize("trigger", ["status", "state"])
def test_run_once_returns_from_hook_while_command_is_running(monkeypatch, trigger):
    cooling = dict(rule("cool", filtering_enabled=True, status_contains="cooling", printer_states="PAUSED"), run_once=True)
    plugin = once_plugin([cooling])
    started = threading.Event()
    finish = threading.Event()
    returned = threading.Event()
    workers = []

    def worker(**kwargs):
        thread = threading.Thread(**kwargs)
        workers.append(thread)
        return thread

    monkeypatch.setattr(sys.modules["octoprint_repeatingcommand"], "Thread", worker)

    def command(cmd):
        plugin.commands.append(cmd)
        started.set()
        assert finish.wait(timeout=5)
        return 0, b"ok"

    plugin.run_command = command

    def activate():
        if trigger == "status":
            plugin.on_gcode_queuing(None, None, "M117 Cooling", None, "M117", None, None)
        else:
            plugin.on_event("PrinterStateChanged", {"state_id": "PAUSED"})
        returned.set()

    caller = threading.Thread(target=activate)
    caller.start()
    try:
        assert started.wait(timeout=2)
        assert returned.wait(timeout=2), "OctoPrint hook waited for the external command"
        activate()
        assert plugin.commands == ["cool"]
        assert len(workers) == 1
        assert workers[0].is_alive()
    finally:
        finish.set()
        caller.join(timeout=5)
        for thread in workers:
            thread.join(timeout=5)
    assert not caller.is_alive()
    assert all(not thread.is_alive() for thread in workers)
