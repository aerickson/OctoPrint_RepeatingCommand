# coding=utf-8


import datetime
import getpass
import os
import re
import shlex
import socket
import subprocess
import time

import octoprint.plugin
import octoprint.util


class RepeatingCommandPlugin(
    octoprint.plugin.EventHandlerPlugin,
    octoprint.plugin.SettingsPlugin,
    octoprint.plugin.AssetPlugin,
    octoprint.plugin.TemplatePlugin,
):
    def __init__(self):
        self.timer = None
        self.print_active = False
        self.current_status = ""
        self.printer_state = ""
        self.timer_rule = None

    def run_command(self, cmd):
        parsed_cmd = shlex.split(cmd)
        try:
            proc = subprocess.Popen(
                parsed_cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT
            )
            out, _err = proc.communicate()
        except OSError as e:
            return (1, e)
        return (proc.returncode, out.rstrip())

    # ~~ SettingsPlugin
    def get_settings_defaults(self):
        return dict(
            enabled=False,
            command="echo 'Hello friend!'",
            interval=90,
            cooling_command="",
            cooling_interval=30,
            cooling_message="cooling",
            cooling_states="",
            rules=[],
            verbose=False,
        )

    def get_settings_restricted_paths(self):
        return dict(
            admin=[
                ["enabled"],
                ["command"],
                ["interval"],
                ["cooling_command"],
                ["cooling_interval"],
                ["cooling_message"],
                ["cooling_states"],
                ["rules"],
                "verbose",
            ],
            user=[],
            never=[],
        )

    def get_settings_version(self):
        return 1

    # ~~ TemplatePlugin
    def get_template_configs(self):
        return [dict(type="settings", name="Repeating Command", custom_bindings=True)]

    def get_assets(self):
        return dict(js=["js/repeatingcommand.js"])

    def runTimerCommand(self):
        the_cmd = self.timer_rule.get("command", "")
        rc, output = self.run_command(the_cmd)
        if self._settings.get(["verbose"]):
            self._logger.info("result code is %s. output: '%s'" % (rc, output))

    def _legacy_rules(self):
        rules = [
            dict(
                command=self._settings.get(["command"]),
                interval=self._settings.get(["interval"]),
                filtering_enabled=False,
                status_contains="",
                printer_states="",
            )
        ]
        cooling_command = self._settings.get(["cooling_command"])
        cooling_message = self._settings.get(["cooling_message"])
        cooling_states = self._settings.get(["cooling_states"])
        if cooling_command or cooling_message or cooling_states:
            rules.append(
                dict(
                    command=cooling_command or self._settings.get(["command"]),
                    interval=self._settings.get(["cooling_interval"]),
                    filtering_enabled=True,
                    status_contains=cooling_message or "",
                    printer_states=cooling_states or "",
                )
            )
        return rules

    def _rules(self):
        rules = self._settings.get(["rules"])
        return rules if rules else self._legacy_rules()

    def _rule_matches(self, rule):
        if not rule.get("filtering_enabled", False):
            return True

        statuses = [
            value.strip().lower()
            for value in (rule.get("status_contains") or "").split(",")
            if value.strip()
        ]
        states = [
            value.strip().lower()
            for value in (rule.get("printer_states") or "").split(",")
            if value.strip()
        ]
        status_match = any(value in self.current_status.lower() for value in statuses)
        state_match = self.printer_state.lower() in states if self.printer_state else False
        return bool(status_match or state_match)

    def _matching_rule(self, filtered_only=False):
        rules = self._rules()
        filtered = [rule for rule in rules if rule.get("filtering_enabled", False)]
        for rule in filtered:
            if self._rule_matches(rule):
                return rule
        if not filtered_only:
            return next(
                (rule for rule in rules if not rule.get("filtering_enabled", False)),
                None,
            )
        return None

    def _desired_rule(self):
        if self.print_active:
            return self._matching_rule()
        return self._matching_rule(filtered_only=True)

    def _refresh_timer(self):
        if not self._settings.get(["enabled"]):
            self.stopTimer()
            return

        rule = self._desired_rule()
        if rule is None:
            self.stopTimer()
            return

        try:
            interval = float(rule.get("interval", 0))
        except (TypeError, ValueError):
            interval = 0
        if interval <= 0:
            self._logger.warning("not starting timer: interval must be greater than zero")
            self.stopTimer()
            return

        if self.timer and self.timer_rule == rule:
            return

        self.stopTimer()
        self.timer_rule = rule
        the_cmd = rule.get("command", "")
        self._logger.info(
            "starting timer to run command '%s' every %s seconds" % (the_cmd, interval)
        )
        self.timer = octoprint.util.RepeatedTimer(
            interval, self.runTimerCommand, run_first=True
        )
        self.timer.start()

    def stopTimer(self):
        if self.timer:
            self._logger.info("stopping timer")
            self.timer.cancel()
            self.timer = None
        self.timer_rule = None

    # ~~ EventPlugin
    def on_event(self, event, payload):
        # TODO: do something on paused (event == 'PrintPaused')? have an option?
        if event == "PrintStarted":
            self.print_active = True
            self._refresh_timer()
        elif event == "PrintDone":
            self.print_active = False
            self._refresh_timer()
        elif event == "PrintFailed":
            self.print_active = False
            self.stopTimer()
        elif event == "PrinterStateChanged":
            self.printer_state = (payload or {}).get("state_id", "") or (payload or {}).get(
                "state_string", ""
            )
            self._refresh_timer()

    def on_gcode_queuing(self, comm_instance, phase, cmd, cmd_type, gcode, subcode, tags):
        """Remember M117 text so a print's end/cooling phase can use its own profile."""
        if (gcode or "").upper() != "M117":
            return

        match = re.match(r"^M117(?:\s+(.+))?$", cmd.strip(), re.IGNORECASE)
        if match:
            self.current_status = match.group(1) or ""
            self._refresh_timer()

    # ~~ Softwareupdate hook
    def get_update_information(self):
        return dict(
            repeatingcommand=dict(
                displayName=self._plugin_name,
                displayVersion=self._plugin_version,
                current=self._plugin_version,
                # version check: github repository
                # type="github_release",
                type="github_commit",
                user="aerickson",
                repo="OctoPrint_RepeatingCommand",
                branch="master",
                # update method: pip
                # - release
                # pip="https://github.com/aerickson/OctoPrint_RepeatingCommand/archive/{target_version}.zip"
                # - master tarball
                pip="https://github.com/aerickson/OctoPrint_RepeatingCommand/archive/{target}.zip",
            )
        )

    def configuration_ok(self):
        return True


__plugin_name__ = "RepeatingCommand"
__plugin_pythoncompat__ = ">=2.7,<4"


def __plugin_load__():
    global __plugin_implementation__
    __plugin_implementation__ = RepeatingCommandPlugin()

    global __plugin_hooks__
    __plugin_hooks__ = {
        "octoprint.plugin.softwareupdate.check_config": __plugin_implementation__.get_update_information,
        "octoprint.comm.protocol.gcode.queuing": __plugin_implementation__.on_gcode_queuing,
    }
