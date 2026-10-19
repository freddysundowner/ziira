import { describe, expect, it } from "vitest";

import { canMove, cleanIdentifiers, groupByStage, identifierRows, isCollect, latestEstimate, liveLines, nextStages, showsCost } from "./lib";
import type { Estimate, JobSummary, Stage, StageRef } from "./types";

const stage = (id: string, role: string | null = null, moves: string[] = []): Stage =>
  ({ id, company_id: "c", code: id, name: id, kind: "open", role, position: 0, is_active: true, moves_to: moves });
const ref = (s: Stage): StageRef => ({ id: s.id, code: s.code, name: s.name, kind: s.kind, role: s.role });
const job = (id: string, status: StageRef): JobSummary => ({ id, status } as JobSummary);

const flow = [stage("a", "initial", ["b", "c"]), stage("b", null, ["c"]), stage("c", "collected")];

describe("the board", () => {
  it("puts each job in its stage's column and keeps the stage order", () => {
    const cols = groupByStage(flow.map(ref), [job("1", ref(flow[1]!)), job("2", ref(flow[0]!)), job("3", ref(flow[1]!))]);
    expect(cols.map((c) => c.jobs.map((j) => j.id))).toEqual([["2"], ["1", "3"], []]);
  });
  it("leaves out jobs whose stage is not a column", () => {
    const cols = groupByStage([ref(flow[0]!)], [job("1", ref(flow[2]!))]);
    expect(cols[0]!.jobs).toEqual([]);
  });
});

describe("moving a card", () => {
  it("accepts only the moves the workflow allows", () => {
    expect(canMove(flow, "a", "c")).toBe(true);
    expect(canMove(flow, "b", "a")).toBe(false);
    expect(canMove(flow, "a", "a")).toBe(false);
    expect(canMove(flow, "zzz", "a")).toBe(false);
  });
  it("lists the next stages in workflow order and spots collection by role", () => {
    expect(nextStages(flow, ["c", "b"]).map((s) => s.id)).toEqual(["b", "c"]);
    expect(isCollect(flow[2]!)).toBe(true);
    expect(isCollect(flow[0]!)).toBe(false);
  });
});

describe("identifiers", () => {
  it("drops blanks, trims and keeps the first of a repeated name", () => {
    expect(cleanIdentifiers([{ name: " plate ", value: " KAA 1 " }, { name: "", value: "x" }, { name: "size", value: "" }, { name: "plate", value: "other" }])).toEqual({ plate: "KAA 1" });
  });
  it("gives an empty row to type into when there is nothing yet", () => {
    expect(identifierRows({})).toEqual([{ name: "", value: "" }]);
    expect(identifierRows({ imei: 123 })).toEqual([{ name: "imei", value: "123" }]);
  });
});

describe("job figures", () => {
  it("counts only lines that were not removed", () => {
    expect(liveLines([{ voided: false, id: 1 }, { voided: true, id: 2 }]).map((l) => l.id)).toEqual([1]);
  });
  it("shows cost only when the server sent one", () => {
    expect(showsCost({ totals: { cost: null } } as never)).toBe(false);
    expect(showsCost({ totals: { cost: "0.0000" } } as never)).toBe(true);
  });
  it("finds the newest estimate version", () => {
    expect(latestEstimate([{ version: 1 }, { version: 3 }, { version: 2 }] as Estimate[])?.version).toBe(3);
    expect(latestEstimate([])).toBeUndefined();
  });
});
