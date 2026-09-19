# OctoPrint_RepeatingCommand

Runs a command at a specified interval during prints.

I use it to trigger my home automation to run an exhaust fan (that normally turns off after 5 minutes) when printing.

![Settings tab screenshot](extras/settings.png)

## Installation

Install via the bundled [Plugin Manager](https://github.com/foosel/OctoPrint/wiki/Plugin:-Plugin-Manager)
or manually using this URL:

    https://github.com/aerickson/OctoPrint_RepeatingCommand/archive/master.zip

For editable development installs, use the Python environment that runs
OctoPrint:

    python -m pip install -e .

## Configuration

Set a command and interval and enable it.

The optional alternate profile is selected when the current `M117` message
contains one of the configured comma-separated substrings (case-insensitive), or
when the printer state matches one of the configured comma-separated state IDs.
For example, set the M117 text to `cooling`, the alternate interval to `10`, and
optionally provide a different command. A blank alternate command reuses the
normal command. This is not tied to a particular printer state: it can be used
for any M117 text or state your printer reports, including `Printing`.

The cooling profile can continue running after `PrintDone` while the cooling
condition remains active. Clear the `M117` message or leave the configured cooling
state to return to the normal profile or stop the timer.

## Acknowledgements

Loosely based on [OctoPrint_FreeMobile-Notifier](https://github.com/Pinaute/OctoPrint_FreeMobile-Notifier).

## License

Licensed under the terms of the [AGPLv3](http://opensource.org/licenses/AGPL-3.0).
