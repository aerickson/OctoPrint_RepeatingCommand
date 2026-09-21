#!/usr/bin/env python3

import argparse
import json
from pathlib import Path

from playwright.sync_api import Page, Playwright, TimeoutError, sync_playwright


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--artifacts", type=Path, required=True)
    parser.add_argument("--headed", action="store_true")
    return parser.parse_args()


def open_settings(page: Page, base_url: str) -> None:
    page.goto(base_url, wait_until="domcontentloaded")
    page.locator("#navbar_show_settings").click()
    page.locator('a[href="#settings_plugin_repeatingcommand"]').click(force=True)
    page.locator("#settings_plugin_repeatingcommand").wait_for(state="visible")
    heads_up = page.get_by_role("button", name="Got it!")
    if heads_up.is_visible():
        heads_up.click()


def rule_fields(page: Page):
    return page.locator("#settings_plugin_repeatingcommand fieldset")


def set_rule(page: Page, index: int, command: str, interval: str, status: str, states: str) -> None:
    rule = rule_fields(page).nth(index)
    text_inputs = rule.locator("input[type=text]")
    text_inputs.nth(0).fill(command)
    rule.locator("input[type=number]").fill(interval)
    rule.locator("input[type=checkbox]").check()
    text_inputs.nth(1).fill(status)
    text_inputs.nth(2).fill(states)


def read_rule(page: Page, index: int) -> dict[str, str | bool]:
    rule = rule_fields(page).nth(index)
    text_inputs = rule.locator("input[type=text]")
    return {
        "command": text_inputs.nth(0).input_value(),
        "interval": rule.locator("input[type=number]").input_value(),
        "filtering_enabled": rule.locator("input[type=checkbox]").is_checked(),
        "status_contains": text_inputs.nth(1).input_value(),
        "printer_states": text_inputs.nth(2).input_value(),
    }


def expected_rule(command: str, interval: str, status: str, states: str) -> dict[str, str | bool]:
    return {
        "command": command,
        "interval": interval,
        "filtering_enabled": True,
        "status_contains": status,
        "printer_states": states,
    }


def record_request_failure(request, request_errors: list[str]) -> None:
    failure = request.failure or ""
    if "ABORTED" in failure.upper() or "ERR_ABORTED" in failure.upper():
        return
    if "/api/settings" in request.url or "repeatingcommand" in request.url:
        request_errors.append(f"{request.method} {request.url}: {failure}")


def run_test(page: Page, base_url: str, new_page) -> None:
    open_settings(page, base_url)
    settings = page.locator("#settings_plugin_repeatingcommand")

    initial_rule_count = rule_fields(page).count()
    assert 1 <= initial_rule_count < 3
    while rule_fields(page).count() < 3:
        settings.get_by_role("button", name="Add Rule").click()
    assert rule_fields(page).count() == 3

    set_rule(page, 0, "echo first", "11", "first", "PRINTING")
    set_rule(page, 1, "echo second", "22", "second", "PAUSED")
    set_rule(page, 2, "echo third", "33", "third", "FINISHING")

    rule_fields(page).nth(2).get_by_role("button", name="Up").click()
    assert read_rule(page, 1)["command"] == "echo third"
    rule_fields(page).nth(0).get_by_role("button", name="Remove").click()
    assert rule_fields(page).count() == 2

    expected = [
        expected_rule("echo third", "33", "third", "FINISHING"),
        expected_rule("echo second", "22", "second", "PAUSED"),
    ]
    assert [read_rule(page, index) for index in range(2)] == expected

    page.get_by_role("button", name="Save").click()
    page.wait_for_load_state("domcontentloaded")
    page.close()
    page = new_page()
    open_settings(page, base_url)
    assert [read_rule(page, index) for index in range(2)] == expected


def main() -> int:
    args = parse_args()
    args.artifacts.mkdir(parents=True, exist_ok=True)
    console_errors: list[str] = []
    page_errors: list[str] = []
    request_errors: list[str] = []
    response_errors: list[str] = []

    with sync_playwright() as playwright:  # type: Playwright
        browser = playwright.firefox.launch(
            headless=not args.headed,
        )
        context = browser.new_context()
        context.tracing.start(screenshots=True, snapshots=True, sources=True)

        def new_page() -> Page:
            page = context.new_page()
            page.on("console", lambda message: console_errors.append(message.text) if message.type == "error" else None)
            page.on("pageerror", lambda error: page_errors.append(str(error)))
            page.on("requestfailed", lambda request: record_request_failure(request, request_errors))
            page.on(
                "response",
                lambda response: (
                    response_errors.append(f"{response.status} {response.url}")
                    if response.status >= 400
                    and (
                        "/api/settings" in response.url
                        or "/static/" in response.url
                        or "/plugin/" in response.url
                    )
                    else None
                ),
            )
            return page

        page = new_page()

        try:
            run_test(page, args.base_url, new_page)
            if console_errors or page_errors or request_errors or response_errors:
                raise AssertionError(
                    json.dumps(
                        {
                            "console_errors": console_errors,
                            "page_errors": page_errors,
                            "request_errors": request_errors,
                            "response_errors": response_errors,
                        },
                        indent=2,
                    )
                )
        except Exception:
            page.screenshot(path=str(args.artifacts / "failure.png"), full_page=True)
            context.tracing.stop(path=str(args.artifacts / "failure-trace.zip"))
            raise
        else:
            context.tracing.stop()
        finally:
            browser.close()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
