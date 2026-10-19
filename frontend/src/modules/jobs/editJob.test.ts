import { describe, expect, it } from "vitest";

import { editForm, jobPatch } from "./editJob";
import type { Job } from "./types";

const job = { title: "Brakes", description: null, condition_notes: "Scratched", customer_id: null, customer_name: "Amina", customer_phone: "0700", asset: { id: "a1" }, assignee_id: null, promised_at: "2026-11-01" } as unknown as Job;

describe("editing a job", () => {
  it("sends nothing when nothing changed", () => {
    expect(jobPatch(job, editForm(job))).toEqual({});
  });
  it("sends only the fields that changed", () => {
    expect(jobPatch(job, { ...editForm(job), title: " Brake pads ", promised: "" })).toEqual({ title: "Brake pads", promised_at: null });
  });
  it("sends a picked customer as an id alone", () => {
    expect(jobPatch(job, { ...editForm(job), customerId: "u1" })).toEqual({ customer_id: "u1" });
  });
  it("sends a typed name and phone when there is no customer record", () => {
    expect(jobPatch(job, { ...editForm(job), customerName: "Amina K", customerPhone: "" })).toEqual({ customer_name: "Amina K", customer_phone: null });
  });
});
