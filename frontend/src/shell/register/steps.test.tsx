import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { Edition } from "@/sdk";

import { COUNTRIES } from "../countries";
import { Creating, CreatingFailed } from "./Creating";
import { PasswordMeter } from "./PasswordMeter";
import { StepAccount } from "./StepAccount";
import { StepBusiness } from "./StepBusiness";
import { StepNeed } from "./StepNeed";
import { StepPassword } from "./StepPassword";
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

describe("the password", () => {
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

describe("step 2: your business", () => {
  const ke = COUNTRIES.find((c) => c.code === "KE")!;
  it("asks only for the business name, the country and the kind; currency, time zone and calling code come from the country", () => {
    render(<Harness initial={{ country: "KE", currency: "KES", zone: "Africa/Nairobi", calling: "254" }}>{(form) => <>
      <StepBusiness form={form} countries={COUNTRIES} country={ke} onCountry={() => undefined} />
      <output data-testid="values">{JSON.stringify([form.values.business, form.values.kind])}</output>
    </>}</Harness>);
    expect(screen.queryByLabelText(/^currency/i)).toBeNull();
    expect(screen.queryByLabelText(/phone calling code/i)).toBeNull();
    expect(screen.queryByLabelText(/time zone/i)).toBeNull();
    expect(screen.queryByLabelText(/tax/i)).toBeNull();
    expect(screen.queryByRole("group", { name: /how many/i })).toBeNull();
    fireEvent.change(screen.getByLabelText(/business name/i), { target: { value: "Acme Traders" } });
    fireEvent.click(screen.getByRole("radio", { name: "Wholesale" }));
    expect(screen.getByTestId("values").textContent).toBe(JSON.stringify(["Acme Traders", "wholesale"]));
  });
});

describe("step 2 with the Services edition: what kind of service business", () => {
  const ke = COUNTRIES.find((c) => c.code === "KE")!;
  const industries = [{ id: "pack_salon", title: "Salon or spa", summary: "Hair, nails, massage." }, { id: "pack_garage", title: "Garage or repair", summary: "" }];
  const show = (edition: string, list = industries) => render(<Harness initial={{ edition, country: "KE", currency: "KES", zone: "Africa/Nairobi", calling: "254" }}>{(form) => <>
    <StepBusiness form={form} countries={COUNTRIES} country={ke} onCountry={() => undefined} industries={list} />
    <output data-testid="kind">{form.values.kind}</output>
  </>}</Harness>);

  it("asks about the kinds the installed packs offer, plus Something else, and records the pack picked", () => {
    show("services");
    expect(screen.getByRole("group", { name: /what kind of service business/i })).toBeTruthy();
    expect(screen.queryByRole("radio", { name: "Wholesale" })).toBeNull();
    expect(screen.getByRole("radio", { name: "Something else" })).toBeTruthy();
    fireEvent.click(screen.getByRole("radio", { name: "Salon or spa" }));
    expect(screen.getByTestId("kind").textContent).toBe("pack_salon");
    expect(screen.getByText("Hair, nails, massage.")).toBeTruthy();
    fireEvent.click(screen.getByRole("radio", { name: "Something else" }));
    expect(screen.getByTestId("kind").textContent).toBe("other");
  });
  it("keeps the usual question for other editions, and when no pack is installed", () => {
    show("retail");
    expect(screen.getByRole("radio", { name: "Wholesale" })).toBeTruthy();
    cleanup();
    show("services", []);
    expect(screen.getByRole("radio", { name: "Wholesale" })).toBeTruthy();
  });
  it("adds the packs recommended for a shop edition (a pharmacy) to the usual choices", () => {
    show("retail", [{ id: "pack_pharmacy", title: "Pharmacy or chemist", summary: "" }]);
    expect(screen.getByRole("radio", { name: "Wholesale" })).toBeTruthy();
    fireEvent.click(screen.getByRole("radio", { name: "Pharmacy or chemist" }));
    expect(screen.getByTestId("kind").textContent).toBe("pack_pharmacy");
  });
});

describe("step 3: your account", () => {
  const values = { email: "jane@acme.test", password: "a-good-password-1", confirm: "a-good-password-1" };
  const account = (initial: Record<string, unknown>, extra: { terms?: string; privacy?: string; serverError?: string | null } = {}) => render(<Harness initial={initial}>{(form) => <>
    <StepAccount form={form} server="ok" serverMessage={null} terms={extra.terms ?? ""} privacy={extra.privacy ?? ""} serverError={extra.serverError ?? null} />
    <output data-testid="values">{JSON.stringify([form.values.email, form.values.consent])}</output>
  </>}</Harness>);

  it("asks for the email, the password twice and the agreement; terms are links only when configured", () => {
    account(values, { terms: "https://example.test/terms/" });
    fireEvent.change(screen.getByLabelText(/work email/i), { target: { value: "owner@acme.test" } });
    expect(screen.getByTestId("values").textContent).toBe(JSON.stringify(["owner@acme.test", false]));
    expect(screen.getByRole("link", { name: "Terms of use" }).getAttribute("href")).toBe("https://example.test/terms/");
    expect(screen.queryByRole("link", { name: "Privacy policy" })).toBeNull();     // no URL configured: plain words
    expect(screen.getByText("Privacy policy")).toBeTruthy();
    expect(screen.queryByLabelText(/full name/i)).toBeNull();
    expect(screen.queryByLabelText(/phone/i)).toBeNull();
  });

  it("suggests the right domain for a typo and applies it on request", () => {
    account({ ...values, email: "jane@gmial.com" });
    expect(screen.getByText("Did you mean jane@gmail.com?")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Yes, use it" }));
    expect((screen.getByLabelText(/work email/i) as HTMLInputElement).value).toBe("jane@gmail.com");
  });

  it("records the consent and shows what the server said", () => {
    account(values, { serverError: "Too many registration attempts" });
    fireEvent.click(screen.getByRole("checkbox"));
    expect(screen.getByTestId("values").textContent).toBe(JSON.stringify(["jane@acme.test", true]));
    expect(screen.getByRole("alert").textContent).toContain("Too many registration attempts");
  });
});

describe("after submit and while creating", () => {
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
