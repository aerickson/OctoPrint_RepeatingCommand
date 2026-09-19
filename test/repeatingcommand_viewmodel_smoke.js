const assert = require("assert");
const fs = require("fs");
const vm = require("vm");

function observable(value) {
    return function(next) {
        if (arguments.length) value = next;
        return value;
    };
}

function observableArray(value) {
    const result = function(next) {
        if (arguments.length) value = next;
        return value;
    };
    result.push = item => value.push(item);
    result.remove = item => {
        value = value.filter(current => current !== item);
    };
    result.indexOf = item => value.indexOf(item);
    result.splice = (...args) => value.splice(...args);
    return result;
}

function loadViewModel() {
    const registrations = [];
    const context = {
        OCTOPRINT_VIEWMODELS: registrations,
        ko: {
            observable,
            observableArray,
            unwrap: value => typeof value === "function" ? value() : value
        }
    };
    vm.runInNewContext(
        fs.readFileSync("octoprint_repeatingcommand/static/js/repeatingcommand.js", "utf8"),
        context
    );
    return registrations[0].construct;
}

function makePluginSettings(values) {
    values = values || {};
    return {
        command: observable(values.command || "echo normal"),
        interval: observable(values.interval || 90),
        cooling_command: observable(values.cooling_command || ""),
        cooling_interval: observable(values.cooling_interval || 10),
        cooling_message: observable(values.cooling_message || ""),
        cooling_states: observable(values.cooling_states || ""),
        rules: values.rules || []
    };
}

function makeInstance(pluginSettings) {
    const settingsViewModel = { settings: {} };
    const instance = new (loadViewModel())([settingsViewModel]);
    settingsViewModel.settings.plugins = { repeatingcommand: pluginSettings };
    instance.onBeforeBinding();
    return instance;
}

function rule(command, interval, filteringEnabled, status, states) {
    return {
        command,
        interval: interval || 90,
        filtering_enabled: !!filteringEnabled,
        status_contains: status || "",
        printer_states: states || ""
    };
}

function testLateSettingsInitialization() {
    const settingsViewModel = { settings: {} };
    const instance = new (loadViewModel())([settingsViewModel]);
    settingsViewModel.settings.plugins = {
        repeatingcommand: makePluginSettings()
    };
    instance.onBeforeBinding();
    assert.strictEqual(instance.pluginSettings.rules().length, 1);
}

function testLegacyConversion() {
    const instance = makeInstance(makePluginSettings({
        command: "normal",
        interval: 90,
        cooling_command: "cooling",
        cooling_interval: 10,
        cooling_message: "cooling"
    }));
    const rules = instance.pluginSettings.rules();
    assert.strictEqual(rules.length, 2);
    assert.strictEqual(rules[1].command(), "cooling");
    assert.strictEqual(rules[1].filtering_enabled(), true);
    assert.strictEqual(rules[1].status_contains(), "cooling");
}

function testSavedRulesAndAddLimit() {
    const saved = [rule("one"), rule("two", 10, true, "cooling")];
    const instance = makeInstance(makePluginSettings({ rules: saved }));
    assert.strictEqual(instance.pluginSettings.rules().length, 2);
    assert.strictEqual(instance.pluginSettings.rules()[1].command(), "two");

    for (let index = 0; index < 10; index += 1) {
        instance.pluginSettings.addRule();
    }
    assert.strictEqual(instance.pluginSettings.rules().length, 6);
}

function testRemoveAndReorder() {
    const instance = makeInstance(makePluginSettings({
        rules: [rule("one"), rule("two"), rule("three")]
    }));
    const rules = instance.pluginSettings.rules();
    instance.pluginSettings.moveRuleDown(rules[0]);
    assert.deepStrictEqual(
        instance.pluginSettings.rules().map(current => current.command()),
        ["two", "one", "three"]
    );
    instance.pluginSettings.moveRuleUp(instance.pluginSettings.rules()[2]);
    assert.deepStrictEqual(
        instance.pluginSettings.rules().map(current => current.command()),
        ["two", "three", "one"]
    );
    instance.pluginSettings.removeRule(instance.pluginSettings.rules()[1]);
    assert.deepStrictEqual(
        instance.pluginSettings.rules().map(current => current.command()),
        ["two", "one"]
    );
}

function testSaveSerialization() {
    const instance = makeInstance(makePluginSettings({ rules: [rule("one")] }));
    const current = instance.pluginSettings.rules()[0];
    current.command("updated");
    current.interval(15);
    current.filtering_enabled(true);
    current.status_contains("cooling");
    current.printer_states("FINISHING");

    instance.onSettingsBeforeSave();
    assert.deepStrictEqual(JSON.parse(JSON.stringify(instance.pluginSettings.rules())), [{
        command: "updated",
        interval: 15,
        filtering_enabled: true,
        status_contains: "cooling",
        printer_states: "FINISHING"
    }]);
}

testLateSettingsInitialization();
testLegacyConversion();
testSavedRulesAndAddLimit();
testRemoveAndReorder();
testSaveSerialization();
console.log("repeating command viewmodel tests: SUCCESS (5 cases)");
