import allure
import pytest
from playwright.sync_api import Page
from slugify import slugify
from playwright_tests.core.utilities import Utilities
from playwright_tests.messages.homepage_messages import HomepageMessages


@pytest.fixture(autouse=True)
def navigate_to_homepage(page: Page):
    """
    This fixture is used in all functions. It navigates to the SuMo homepage and returns the page
    object.
    """
    utilities = Utilities(page)
    # Set default navigation timeout to 2 minutes.
    page.set_default_navigation_timeout(120000)

    # Block pontoon requests in the current page context.
    page.route("**/pontoon.mozilla.org/**", utilities.block_request)

    # Navigate to the SUMO stage homepage.
    page.goto(HomepageMessages.STAGE_HOMEPAGE_URL)

    return page


def pytest_runtest_makereport(item, call) -> None:
    """
    This pytest hook is triggered after each test execution.
    If a test failure occurred we are saving & attaching the test execution screencast to the
    allure report for better debugging.
    """
    if call.when == "call":
        # Check if the test has raised an exception (test failed or encountered an error during
        # execution). Also checks if the test function has the page instance in its arguments
        # ensuring that video recording is applied only when the test involves playwright
        # automation.
        if call.excinfo is not None and "page" in item.funcargs:
            # Retrieve the page object from the test function arguments.
            page: Page = item.funcargs["page"]
            # Provide the path to the recorded video (the video recording starts when the browser
            # context is created).
            video_path = page.video.path()
            # Ensure that the browser context is closed after test. Closing the context also
            # ensures that the video is properly saved.
            page.context.close()
            # Attaching the video to the Allure report:
            # 1. Opening the video file in binary mode and reading its content.
            # 2. Assigning a name to the video attachment based on the slugyfied version of the
            # test node id.
            # 3. Saving the video as a .webm extension.
            allure.attach(
                open(video_path, 'rb').read(),
                name=f"{slugify(item.nodeid)}.webm",
                attachment_type=allure.attachment_type.WEBM
            )


@pytest.fixture()
def browser_context_args(browser_context_args, tmpdir_factory: pytest.TempdirFactory):
    """
    Modifying the default browser context to include the location of the browser session screencast
    """
    return {
        **browser_context_args,
        "record_video_dir": tmpdir_factory.mktemp('videos')
    }
