import { describe, expect, it } from "vitest";

import { type AttachedFile, checkChoice, encodeHeader, fitWithin, formatBytes, groupByCategory, isRetryable, retryDelaySeconds } from "./logic";

const config = { max_file_bytes: 10 * 1024 * 1024 };
const choice = (name: string, type: string, size = 1000) => ({ name, type, size });

describe("checkChoice", () => {
  it("accepts pictures and PDFs, even when the browser gives no type", () => {
    for (const f of [choice("a.jpg", "image/jpeg"), choice("a.png", "image/png"), choice("a.webp", "image/webp"), choice("a.pdf", "application/pdf"), choice("PHOTO.JPG", "")]) {
      expect(checkChoice(f, config, 0, 60)).toBeNull();
    }
  });
  it("names the reason for each refusal", () => {
    expect(checkChoice(choice("a.exe", "application/x-msdownload"), config, 0, 60)).toBe("type");
    expect(checkChoice(choice("a.docx", ""), config, 0, 60)).toBe("type");
    expect(checkChoice(choice("a.heic", "image/heic"), config, 0, 60)).toBe("heic");
    expect(checkChoice(choice("a.jpg", "image/jpeg", 0), config, 0, 60)).toBe("empty");
    expect(checkChoice(choice("a.jpg", "image/jpeg", 11 * 1024 * 1024), config, 0, 60)).toBe("tooBig");
    expect(checkChoice(choice("a.jpg", "image/jpeg"), config, 60, 60)).toBe("full");
  });
});

describe("helpers", () => {
  it("writes sizes in plain units", () => {
    expect(formatBytes(512)).toBe("512 B");
    expect(formatBytes(2048)).toBe("2 KB");
    expect(formatBytes(3.5 * 1024 * 1024)).toBe("3.5 MB");
  });
  it("percent-encodes header text as UTF-8", () => {
    expect(encodeHeader(" Bumper ya mbele ✓ ")).toBe("Bumper%20ya%20mbele%20%E2%9C%93");
    expect(decodeURIComponent(encodeHeader("gari – mbele.jpg"))).toBe("gari – mbele.jpg");
  });
  it("shrinks to fit a long side and never enlarges", () => {
    expect(fitWithin(4000, 3000, 2560)).toEqual({ width: 2560, height: 1920 });
    expect(fitWithin(3000, 4000, 2560)).toEqual({ width: 1920, height: 2560 });
    expect(fitWithin(800, 600, 2560)).toEqual({ width: 800, height: 600 });
  });
  it("retries what a connection or a busy server caused, not what a person must fix", () => {
    for (const s of [0, 408, 429, 500, 503]) expect(isRetryable(s)).toBe(true);
    for (const s of [400, 401, 403, 404, 413, 422]) expect(isRetryable(s)).toBe(false);
    expect([1, 2, 3, 4, 5, 6, 10].map(retryDelaySeconds)).toEqual([5, 10, 20, 40, 80, 160, 300]);
  });
});

describe("groupByCategory", () => {
  const file = (id: string, category: string) => ({ id, category }) as AttachedFile;
  it("keeps the kinds in the unit's order, leaves out empty kinds and adds unknown ones last", () => {
    const groups = groupByCategory([file("1", "damage"), file("2", "intake"), file("3", "old_part"), file("4", "damage")],
      [{ key: "intake", label: "Intake" }, { key: "damage", label: "Damage" }, { key: "progress", label: "Progress" }]);
    expect(groups.map((g) => [g.label, g.files.map((f) => f.id)])).toEqual([["Intake", ["2"]], ["Damage", ["1", "4"]], ["Old part", ["3"]]]);
  });
});
