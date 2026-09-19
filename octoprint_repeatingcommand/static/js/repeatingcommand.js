/* global OCTOPRINT_VIEWMODELS, ko */

function RepeatingCommandViewModel(parameters) {
    var self = this;
    self.settingsViewModel = parameters[0];
    self.settings = null;
    self.pluginSettings = null;
    self.maxRules = 6;
    var initialRules = [];

    function rule(data) {
        data = data || {};
        return {
            command: ko.observable(ko.unwrap(data.command) || ""),
            interval: ko.observable(ko.unwrap(data.interval) || 90),
            filtering_enabled: ko.observable(!!ko.unwrap(data.filtering_enabled)),
            status_contains: ko.observable(ko.unwrap(data.status_contains) || ""),
            printer_states: ko.observable(ko.unwrap(data.printer_states) || "")
        };
    }

    function legacyRules() {
        var normal = rule({
            command: ko.unwrap(self.pluginSettings.command),
            interval: ko.unwrap(self.pluginSettings.interval)
        });
        var coolingCommand = ko.unwrap(self.pluginSettings.cooling_command);
        var coolingMessage = ko.unwrap(self.pluginSettings.cooling_message);
        var coolingStates = ko.unwrap(self.pluginSettings.cooling_states);
        if (coolingCommand || coolingMessage || coolingStates) {
            return [normal, rule({
                command: coolingCommand || ko.unwrap(self.pluginSettings.command),
                interval: ko.unwrap(self.pluginSettings.cooling_interval),
                filtering_enabled: true,
                status_contains: coolingMessage,
                printer_states: coolingStates
            })];
        }
        return [normal];
    }

    function fromSettings() {
        var saved = initialRules.length ? initialRules : ko.unwrap(self.pluginSettings.rules) || [];
        self.pluginSettings.rules(saved.length ? saved.map(rule) : legacyRules());
        initialRules = [];
    }

    function plainRules() {
        return self.pluginSettings.rules().map(function(current) {
            return {
                command: ko.unwrap(current.command),
                interval: ko.unwrap(current.interval),
                filtering_enabled: ko.unwrap(current.filtering_enabled),
                status_contains: ko.unwrap(current.status_contains),
                printer_states: ko.unwrap(current.printer_states)
            };
        });
    }

    function initialize() {
        self.settings = self.settingsViewModel.settings || self.settingsViewModel;
        if (!self.settings.plugins || !self.settings.plugins.repeatingcommand) {
            return false;
        }

        self.pluginSettings = self.settings.plugins.repeatingcommand;
        initialRules = ko.unwrap(self.pluginSettings.rules) || [];
        self.pluginSettings.rules = ko.observableArray([]);
        self.pluginSettings.addRule = function() {
            if (self.pluginSettings.rules().length < self.maxRules) {
                self.pluginSettings.rules.push(rule());
            }
        };
        self.pluginSettings.removeRule = function(current) {
            self.pluginSettings.rules.remove(current);
        };
        self.pluginSettings.moveRuleUp = function(current) {
            var index = self.pluginSettings.rules.indexOf(current);
            if (index > 0) {
                self.pluginSettings.rules.splice(index, 1);
                self.pluginSettings.rules.splice(index - 1, 0, current);
            }
        };
        self.pluginSettings.moveRuleDown = function(current) {
            var index = self.pluginSettings.rules.indexOf(current);
            if (index >= 0 && index < self.pluginSettings.rules().length - 1) {
                self.pluginSettings.rules.splice(index, 1);
                self.pluginSettings.rules.splice(index + 1, 0, current);
            }
        };
        return true;
    }

    self.onBeforeBinding = function() {
        if (initialize()) {
            fromSettings();
        }
    };

    self.onSettingsShown = function() {
        if (self.pluginSettings || initialize()) {
            fromSettings();
        }
    };

    self.onSettingsBeforeSave = function() {
        if (self.pluginSettings) {
            self.pluginSettings.rules(plainRules());
        }
    };
}

OCTOPRINT_VIEWMODELS.push({
    construct: RepeatingCommandViewModel,
    dependencies: ["settingsViewModel"],
    elements: ["#settings_plugin_repeatingcommand"]
});
