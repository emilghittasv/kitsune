import trackEvent from "sumo/js/analytics";
import { BaseFormStep } from "sumo/js/form-wizard";
import { ReminderDialog } from "sumo/js/form-wizard-reminder-dialog"
import setupDeviceStepStyles from "../scss/form-wizard-setup-device-step.styles.scss";
import successIconUrl from "sumo/img/success-white.svg";

const ERROR_TYPES = Object.freeze({
  INVALID_EMAIL: "invalid-email",
  OTHER: "other",
});

export class SetupDeviceStep extends BaseFormStep {
  #reminderDialog = null;
  #formEl = null;
  #emailEl = null;
  #emailErrorEl = null;
  #submitButton = null;

  get template() {
    return `
      <template>
        <div id="setup-device-root">
          <h3>${gettext("Download Firefox on your new device")}</h3>
          <ul>
            <li>${gettext("Send this link to your email, or download it directly from the Firefox website. To finish, you'll need to install Firefox and sign in to your account.")}</li>
          </ul>
          <div class="email-calendar-wrapper">
            <form id="email-reminder-form" action="https://basket.mozilla.org/news/subscribe/" method="POST" novalidate="">
              <input type="hidden" name="newsletters" value="download-firefox-desktop-migration">
              <input type="hidden" name="source-url" value="${window.location.href}">
              <input type="hidden" name="lang" value="${navigator.language}">

              <label for="email">${gettext("Enter your email address")}</label>
              <div class="tooltip-container">
                <aside id="email-error" class="tooltip">
                  <span class="invalid-email error">${gettext("Invalid email address")}</span>
                  <span class="other error">${gettext("An error occurred in our system. Please try again later.")}</span>
                </aside>
                <input id="email" name="email" type="email" required="true" placeholder="${gettext("example@example.com")}"/>
                <button id="submit" type="submit" class="mzp-c-button mzp-t-product mzp-t-lg" data-event-name="dmw_click" data-event-parameters='{"dmw_click_target": "send-email-reminder"}' disabled="">
                  <span class="not-success">${gettext("Send link")}</span>
                  <img class="success" src="${successIconUrl}" aria-hidden="true"/>
                  <span class="success">${gettext("Sent")}</span>
                </button>
              </div>
              <div id="email-consent-message">${interpolate(
                gettext("The intended recipient of the email must have consented. <a href='%s'>Learn more</a>"),
                ["https://www.mozilla.org/en-US/privacy/websites/#campaigns"]
              )}</div>
            </form>
            <button id="open-reminder-dialog-button" class="mzp-c-button mzp-t-product mzp-t-secondary" data-event-name="dmw_click" data-event-parameters='{"dmw_click_target": "open-reminder-dialog"}'>${gettext("Add to calendar")}</button>
          </div>
        </div>
      </template>
    `;
  }

  get styles() {
    let linkEl = document.createElement("link");
    linkEl.rel = "stylesheet";
    linkEl.href = setupDeviceStepStyles;
    return linkEl;
  }

  constructor() {
    super();
  }

  connectedCallback() {
    super.connectedCallback();
    let reminderDialogButton = this.shadowRoot.getElementById("open-reminder-dialog-button");
    reminderDialogButton.addEventListener("click", this);

    this.#formEl = this.shadowRoot.getElementById("email-reminder-form");
    this.#emailEl = this.shadowRoot.getElementById("email");
    this.#emailErrorEl = this.shadowRoot.getElementById("email-error");

    this.#formEl.addEventListener("submit", this);
    this.#emailEl.addEventListener("blur", this);
    this.#emailEl.addEventListener("input", this);
    this.#submitButton = this.shadowRoot.getElementById("submit");

    let lang = document.documentElement.getAttribute("lang");
    if (lang) {
      // If we found the document language, update the one that we'll
      // request the email in. This defaults to navigator.language as
      // a safe fallback in the event that lang isn't defined for some
      // reason.
      let langEl = this.#formEl.querySelector("input[name=lang]");
      langEl.value = lang;
    }

    // If the user went through Step 1 and gave us an email address,
    // it got stored in session storage, so we can prefill the email
    // field here.
    try {
      let step1Email = sessionStorage.getItem("switching-devices-email");
      this.#emailEl.value = step1Email;
      this.#onInput();
    } catch (e) {
      // We wrap this in a try/catch because session storage methods might
      // throw if the user has disabled cookies or other types of site
      // data storage, and we want this to be non-fatal.
    }
  }

  handleEvent(event) {
    switch (event.type) {
      case "click": {
        this.#onClick(event);
        break;
      }
      case "blur": {
        if (!this.#emailEl.validity.valid) {
          this.#showError(ERROR_TYPES.INVALID_EMAIL);
        }
        break;
      }
      case "input": {
        this.#onInput();
        break;
      }
      case "submit": {
        if (!this.#emailEl.validity.valid) {
          this.#showError(ERROR_TYPES.INVALID_EMAIL);
          event.preventDefault();
          return;
        }

        event.preventDefault();
        this.#submitEmail();

        break;
      }
    }
  }

  #onInput() {
    if (this.#emailEl.value?.trim()) {
      this.#hideError();
    }

    this.#submitButton.toggleAttribute("success", false);
    this.#submitButton.disabled = !this.#emailEl.validity.valid;
  }

  #onClick(event) {
    if (event.target.id == "open-reminder-dialog-button") {
      this.#hideError();
      this.openReminderDialog();
    }
  }

  /**
   * Submits the provided email to Basket to subscribe the user to a one-time
   * newsletter that gives them a link to download Firefox on their new device.
   */
  async #submitEmail() {
    trackEvent("dmw_reminder_email_submit");

    this.#submitButton.disabled = true;

    let params = new URLSearchParams();
    for (let element of this.#formEl.elements) {
      // Since the button is inside of the <form> element, it'll get included as one
      // of the form elements, but it's of no value to the request we're sending.
      if (element.id != "submit") {
        params.set(element.name, element.value);
      }
    }

    let response;
    let responseBody;

    try {
      response = await window.fetch(this.#formEl.action, {
        method: this.#formEl.method,
        headers: {
          "Content-Type": "application/x-www-form-urlencoded",
        },
        body: params,
      });
      responseBody = await response.json();
    } catch (e) {
      this.#submitButton.disabled = false;
      this.#showError(ERROR_TYPES.OTHER);

      let event = new CustomEvent(
        "DeviceMigrationWizard:SetupDeviceStep:EmailSubmitted",
        { bubbles: true }
      );
      this.dispatchEvent(event);
      return;
    }

    if (response.status >= 200 &&
        response.status < 300 &&
        responseBody.status == "ok") {
      this.#submitButton.toggleAttribute("success", true);
      trackEvent("dmw_reminder_email_success");
    } else {
      this.#showError(ERROR_TYPES.OTHER);
      this.#submitButton.disabled = false;

      if (responseBody.status) {
        trackEvent("dmw_reminder_email_error", {
          "status": responseBody.status
        });
      } else {
        trackEvent("dmw_reminder_email_error", {
          "status": response.status
        });
      }
    }

    let event = new CustomEvent(
      "DeviceMigrationWizard:SetupDeviceStep:EmailSubmitted",
      { bubbles: true }
    );
    this.dispatchEvent(event);
  }

  #showError(errorType) {
    this.#emailErrorEl.setAttribute("error-type", errorType);
    this.#emailErrorEl.classList.add("visible");
  }

  #hideError() {
    this.#emailErrorEl.classList.remove("visible");
  }

  /**
   * Opens the dialog to create calendar events to remind the user
   * to download and install Firefox in the future.
   *
   * This is currently a public method to facilitate easier manual
   * testing, as the step that will eventually present a button for
   * opening the dialog isn't ready yet.
   */
  openReminderDialog() {
    if (!this.#reminderDialog) {
      let dialog = new ReminderDialog();
      dialog.classList.add("reminder-dialog");
      document.body.appendChild(dialog);

      this.#reminderDialog = dialog;
    }

    this.#reminderDialog.showModal();
  }
}
customElements.define("setup-device-step", SetupDeviceStep);
