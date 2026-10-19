import { describe, expect, it } from "vitest";

import en from "../i18n/en.json";
import sw from "../i18n/sw.json";

describe("note wording", () => {
  it("has the same note keys in English and Swahili", () => {
    expect(Object.keys(sw.note).sort()).toEqual(Object.keys(en.note).sort());
  });
  it("names the links and states plainly", () => {
    expect(en.note).toMatchObject({ see: "See today's note", sendOne: "Send me one now", sent: "Sent", alreadySent: "Already sent today", switch: "Send me a note" });
    expect(en.tabTeam).toBe("Team");
  });
});
