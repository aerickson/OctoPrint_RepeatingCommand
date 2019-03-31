# coding=utf-8


import datetime
import getpass
import os
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
            enabled=False, command="echo 'Hello friend!'", verbose=False, interval=90
        )

    def get_settings_restricted_paths(self):
        return dict(admin=[["enabled"], ["command"], ["interval"]], user=[], never=[])

    def get_settings_version(self):
        return 1

    # ~~ TemplatePlugin
    def get_template_configs(self):
        return [dict(type="settings", name="Repeating Command", custom_bindings=False)]

    def runTimerCommand(self):
        the_cmd = self._settings.get(["command"])
        rc, output = self.run_command(the_cmd)
        if self._settings.get(["verbose"]):
            self._logger.info("result code is %s. output: '%s'" % (rc, output))

    def startTimer(self):
        interval = self._settings.get_float(["interval"])
        the_cmd = self._settings.get(["command"])
        self._logger.info(
            "starting timer to run command '%s' every %s seconds" % (the_cmd, interval)
        )
        self.timer = octoprint.util.RepeatedTimer(
            interval, self.runTimerCommand, run_first=True
        )
        self.timer.start()

    def stopTimer(self):
        self._logger.info("stopping timer")
        if self.timer:
            self.timer.cancel()

    # ~~ EventPlugin
    def on_event(self, event, payload):
        # TODO: do something on paused (event == 'PrintPaused')? have an option?
        if event == "PrintStarted":
            if self._settings.get(["enabled"]):
                self.startTimer()
        elif event == "PrintDone" or event == "PrintFailed":
            self.stopTimer()

    ##~~ Softwareupdate hook
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


def __plugin_load__():
    global __plugin_implementation__
    __plugin_implementation__ = RepeatingCommandPlugin()

    global __plugin_hooks__
    __plugin_hooks__ = {
        "octoprint.plugin.softwareupdate.check_config": __plugin_implementation__.get_update_information
    }
