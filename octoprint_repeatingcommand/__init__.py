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
        self.cooling_message = ""
        self.printer_state = ""
        self.cooling = False
        self.timer_profile = None

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
                "verbose",
            ],
            user=[],
            never=[],
        )

    def get_settings_version(self):
        return 1

    # ~~ TemplatePlugin
    def get_template_configs(self):
        return [dict(type="settings", name="Repeating Command", custom_bindings=False)]

    def runTimerCommand(self):
        the_cmd = self._command_for_profile(self.timer_profile)
        rc, output = self.run_command(the_cmd)
        if self._settings.get(["verbose"]):
            self._logger.info("result code is %s. output: '%s'" % (rc, output))

    def _command_for_profile(self, profile):
        if profile == "cooling":
            cooling_command = self._settings.get(["cooling_command"])
            return cooling_command or self._settings.get(["command"])
        return self._settings.get(["command"])

    def _cooling_condition(self):
        messages = [
            message.strip().lower()
            for message in (self._settings.get(["cooling_message"]) or "").split(",")
            if message.strip()
        ]
        message_match = any(
            message in self.cooling_message.lower() for message in messages
        )
        states = [
            state.strip().lower()
            for state in (self._settings.get(["cooling_states"]) or "").split(",")
            if state.strip()
        ]
        state_match = self.printer_state.lower() in states if self.printer_state else False
        return bool(message_match or state_match)

    def _desired_profile(self):
        if self.cooling:
            return "cooling"
        if self.print_active:
            return "normal"
        return None

    def _refresh_timer(self):
        if not self._settings.get(["enabled"]):
            self.stopTimer()
            return

        profile = self._desired_profile()
        if profile is None:
            self.stopTimer()
            return

        interval = self._settings.get_float(
            ["cooling_interval"] if profile == "cooling" else ["interval"]
        )
        if interval <= 0:
            self._logger.warning("not starting timer: interval must be greater than zero")
            self.stopTimer()
            return

        if self.timer and self.timer_profile == profile:
            return

        self.stopTimer()
        self.timer_profile = profile
        the_cmd = self._command_for_profile(profile)
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
        self.timer_profile = None

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
            self.cooling = False
            self.stopTimer()
        elif event == "PrinterStateChanged":
            self.printer_state = (payload or {}).get("state_id", "") or (payload or {}).get(
                "state_string", ""
            )
            self.cooling = self._cooling_condition()
            self._refresh_timer()

    def on_gcode_queuing(self, comm_instance, phase, cmd, cmd_type, gcode, subcode, tags):
        """Remember M117 text so a print's end/cooling phase can use its own profile."""
        if (gcode or "").upper() != "M117":
            return

        match = re.match(r"^M117(?:\s+(.+))?$", cmd.strip(), re.IGNORECASE)
        if match:
            self.cooling_message = match.group(1) or ""
            self.cooling = self._cooling_condition()
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
