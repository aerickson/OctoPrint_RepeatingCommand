const assert = require("assert");
const fs = require("fs");
const vm = require("vm");

const registrations = [];

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

const ViewModel = registrations[0].construct;
const pluginSettings = {
    command: observable("echo normal"),
    interval: observable(90),
    cooling_command: observable(""),
    cooling_interval: observable(10),
    cooling_message: observable(""),
    cooling_states: observable(""),
    rules: []
};
const viewModel = new ViewModel([{
    settings: { plugins: { repeatingcommand: pluginSettings } }
}]);

viewModel.onSettingsShown();
assert.strictEqual(viewModel.pluginSettings.rules().length, 1);
viewModel.pluginSettings.addRule();
assert.strictEqual(viewModel.pluginSettings.rules().length, 2);

console.log("repeating command viewmodel smoke test: SUCCESS");
