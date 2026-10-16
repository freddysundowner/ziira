import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { Edition } from "@/sdk";

import { EditionCards } from "./EditionCards";

const edition = (id: string, title: string): Edition => ({
  id, title, pitch: `${title} pitch`, units: [], plugin_categories: [], menu_groups: [], landing: "", checklist: [], sample_data: [],
});
const choices = [edition("retail", "Retail"), edition("books", "Books"), edition("brand-new", "Brand new")];

afterEach(cleanup);

describe("EditionCards", () => {
  it("shows a card for each edition, with the chosen one selected", () => {
    render(<EditionCards choices={choices} value="books" onChange={() => undefined} />);
    expect(screen.getAllByRole("radio")).toHaveLength(3);
    expect((screen.getByRole("radio", { name: /books/i }) as HTMLInputElement).checked).toBe(true);
    expect((screen.getByRole("radio", { name: /retail/i }) as HTMLInputElement).checked).toBe(false);
  });

  it("falls back to the server's words for an edition it has no translation for", () => {
    render(<EditionCards choices={choices} value="retail" onChange={() => undefined} />);
    expect(screen.getByText("Brand new")).toBeTruthy();
    expect(screen.getByText("Brand new pitch")).toBeTruthy();
  });

  it("reports the edition picked", () => {
    const onChange = vi.fn();
    render(<EditionCards choices={choices} value="retail" onChange={onChange} />);
    fireEvent.click(screen.getByRole("radio", { name: /books/i }));
    expect(onChange).toHaveBeenCalledWith("books");
  });
});
