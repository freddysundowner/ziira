import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { Edition } from "@/sdk";

import { COUNTRIES } from "../countries";
import { CheckEmail } from "./CheckEmail";
import { Creating, CreatingFailed } from "./Creating";
import { PasswordMeter } from "./PasswordMeter";
import { StepAbout } from "./StepAbout";
import { StepBusiness } from "./StepBusiness";
import { StepNeed } from "./StepNeed";
import { StepPassword } from "./StepPassword";
import { StepReview } from "./StepReview";
import { Harness } from "./testHarness";

afterEach(cleanup);

const edition = (id: string, title: string): Edition => ({ id, title, pitch: `${title} pitch`, units: [], plugin_categories: [], menu_groups: [], landing: "", checklist: [], sample_data: [] });
const choices = [edition("retail", "Retail"), edition("full", "Everything")];

describe("step 1: what do you need", () => {
  it("shows the editions and records the pick", () => {
    render(<Harness initial={{ edition: "full" }}>{(form) => <>
      <StepNeed form={form} choices={choices} loading={false} failed={false} onRetry={() => undefined} />
      <output data-testid="edition">{form.values.edition}</output>
    </>}</Harness>);
    expect((screen.getByRole("radio", { name: /everything/i }) as HTMLInputElement).checked).toBe(true);
    fireEvent.click(screen.getByRole("radio", { name: /retail/i }));
    expect(screen.getByTestId("edition").textContent).toBe("retail");
  });

  it("offers a retry when the choices cannot be loaded", () => {
    const retry = vi.fn();
    render(<Harness>{(form) => <StepNeed form={form} choices={undefined} loading={false} failed onRetry={retry} />}</Harness>);
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(retry).toHaveBeenCalled();
  });
});

describe("step 2: about you", () => {
  it("collects name, email, phone and role, and shows a field's problem", () => {
    render(<Harness errors={{ email: "That email address does not look right." }}>{(form) => <>
      <StepAbout form={form} />
      <output data-testid="values">{JSON.stringify([form.values.name, form.values.email, form.values.phone, form.values.role])}</output>
    </>}</Harness>);
    fireEvent.change(screen.getByLabelText(/your full name/i), { target: { value: "Jane Doe" } });
    fireEvent.change(screen.getByLabelText(/work email/i), { target: { value: "jane@acme.test" } });
    fireEvent.change(screen.getByLabelText(/phone/i), { target: { value: "0712 345 678" } });
    fireEvent.click(screen.getByRole("radio", { name: "Accountant" }));
    expect(screen.getByTestId("values").textContent).toBe(JSON.stringify(["Jane Doe", "jane@acme.test", "0712 345 678", "accountant"]));
    expect(screen.getByRole("alert").textContent).toContain("does not look right");
    expect(screen.getByLabelText(/work email/i).getAttribute("aria-invalid")).toBe("true");
  });

  it("suggests the right domain for a typo and applies it on request", () => {
    render(<Harness initial={{ email: "jane@gmial.com" }}>{(form) => <StepAbout form={form} />}</Harness>);
    expect(screen.getByText("Did you mean jane@gmail.com?")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Yes, use it" }));
    expect((screen.getByLabelText(/work email/i) as HTMLInputElement).value).toBe("jane@gmail.com");
    expect(screen.queryByText(/did you mean/i)).toBeNull();
  });
});

describe("step 3: the password", () => {
  it("has show/hide and a confirmation, and keeps both fields as password boxes until shown", () => {
    render(<Harness initial={{ password: "abcdefghij", confirm: "abcdefghij" }}>{(form) => <StepPassword form={form} server="ok" serverMessage={null} />}</Harness>);
    const password = screen.getByLabelText(/^password/i) as HTMLInputElement;
    expect(password.type).toBe("password");
    fireEvent.click(screen.getByRole("button", { name: "Show password" }));
    expect(password.type).toBe("text");
    expect((screen.getByLabelText(/type the password again/i) as HTMLInputElement).type).toBe("text");
    expect(screen.getByRole("button", { name: "Hide password" })).toBeTruthy();
  });

  it("shows the live rules and the server's plain message when it refuses", () => {
    const rules = { length: true, long: false, notEmail: true };
    render(<PasswordMeter password="password1" rules={rules} server="refused" serverMessage="That password is too easy to guess: choose something less common" matches={false} />);
    expect(screen.getByText("At least 8 characters")).toBeTruthy();
    expect(screen.getByText("12 or more is better")).toBeTruthy();
    expect(screen.getByText("Both passwords match")).toBeTruthy();
    expect(screen.getByRole("alert").textContent).toContain("too easy to guess");
  });
});

describe("step 4: your business", () => {
  const ke = { ...COUNTRIES.find((c) => c.code === "KE")!, taxIdLabel: "KRA PIN", taxIdPattern: "^[AP]\\d{9}[A-Z]$" };
  it("labels the tax number with the country's name for it and shows the pattern", () => {
    render(<Harness initial={{ country: "KE", currency: "KES", zone: "Africa/Nairobi", calling: "254" }}>{(form) =>
      <StepBusiness form={form} countries={COUNTRIES} currencies={["KES", "USD"]} country={ke} onCountry={() => undefined} />}</Harness>);
    expect(screen.getByLabelText(/KRA PIN/)).toBeTruthy();
    expect(screen.getByText(/Format: \^\[AP\]/)).toBeTruthy();
    expect((screen.getByLabelText(/^currency/i) as HTMLSelectElement).value).toBe("KES");
    expect((screen.getByLabelText(/phone calling code/i) as HTMLInputElement).value).toBe("254");
  });

  it("records the business name and the size and kind of business", () => {
    render(<Harness initial={{ country: "KE", currency: "KES", zone: "Africa/Nairobi", calling: "254" }}>{(form) => <>
      <StepBusiness form={form} countries={COUNTRIES} currencies={["KES"]} country={ke} onCountry={() => undefined} />
      <output data-testid="values">{JSON.stringify([form.values.business, form.values.branches, form.values.staff, form.values.kind])}</output>
    </>}</Harness>);
    fireEvent.change(screen.getByLabelText(/business name/i), { target: { value: "Acme Traders" } });
    fireEvent.click(screen.getByRole("radio", { name: "2 to 5" }));
    fireEvent.click(within(screen.getByRole("group", { name: /how many people/i })).getByRole("radio", { name: "6 to 20" }));
    fireEvent.click(screen.getByRole("radio", { name: "Wholesale" }));
    expect(screen.getByTestId("values").textContent).toBe(JSON.stringify(["Acme Traders", "2-5", "6-20", "wholesale"]));
  });
});

describe("step 5: review", () => {
  const values = { name: "Jane Doe", email: "jane@acme.test", business: "Acme Traders", country: "KE", currency: "KES", zone: "Africa/Nairobi", password: "a-good-password-1" };
  it("summarises the answers (never the password), links back to each part and shows the terms links only when configured", () => {
    const onEdit = vi.fn();
    render(<Harness initial={values}>{(form) =>
      <StepReview form={form} edition={choices[0]} country={COUNTRIES.find((c) => c.code === "KE")} terms="https://example.test/terms/" privacy="" onEdit={onEdit} serverError={null} />}</Harness>);
    expect(screen.getByText("Jane Doe")).toBeTruthy();
    expect(screen.getByText("Acme Traders")).toBeTruthy();
    expect(screen.getByText("Kenya")).toBeTruthy();
    expect(screen.queryByText("a-good-password-1")).toBeNull();
    expect(screen.getByRole("link", { name: "Terms of use" }).getAttribute("href")).toBe("https://example.test/terms/");
    expect(screen.queryByRole("link", { name: "Privacy policy" })).toBeNull();     // no URL configured: plain words
    expect(screen.getByText("Privacy policy")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Edit: Your business" }));
    expect(onEdit).toHaveBeenCalledWith("business");
  });

  it("records the consent and shows what the server said", () => {
    render(<Harness initial={values}>{(form) => <>
      <StepReview form={form} edition={undefined} country={undefined} terms="" privacy="" onEdit={() => undefined} serverError="Too many registration attempts" />
      <output data-testid="consent">{String(form.values.consent)}</output>
    </>}</Harness>);
    fireEvent.click(screen.getByRole("checkbox"));
    expect(screen.getByTestId("consent").textContent).toBe("true");
    expect(screen.getByRole("alert").textContent).toContain("Too many registration attempts");
  });
});

describe("after submit and while creating", () => {
  it("tells the person to check their email and offers the development link", () => {
    render(<MemoryRouter><CheckEmail email="jane@acme.test" devToken="zg_abc" onChange={() => undefined} /></MemoryRouter>);
    expect(screen.getByRole("heading", { name: "Check your email" })).toBeTruthy();
    expect(screen.getByText(/jane@acme\.test/)).toBeTruthy();
    expect(screen.getByRole("link", { name: "Open the verification link" }).getAttribute("href")).toBe("/register/verify?token=zg_abc");
  });

  it("shows an honest wait, with no percentage, then a slow notice or a retry notice", () => {
    const { rerender } = render(<Creating slow={false} retrying={false} />);
    expect(screen.getByRole("heading", { name: "Creating your business" })).toBeTruthy();
    expect(screen.queryByText(/%/)).toBeNull();
    rerender(<Creating slow retrying={false} />);
    expect(screen.getByText(/Still working/)).toBeTruthy();
    rerender(<Creating slow retrying />);
    expect(screen.getByText(/Trying once more/)).toBeTruthy();
  });

  it("explains a failure, keeps the reference and lets the person try again", () => {
    const retry = vi.fn();
    render(<MemoryRouter><CreatingFailed message="Your business could not be created right now." requestId="req-123" canRetry blockedUntil={null} onRetry={retry} /></MemoryRouter>);
    expect(screen.getByText("Reference: req-123")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Try again" }));
    expect(retry).toHaveBeenCalled();
  });
});
