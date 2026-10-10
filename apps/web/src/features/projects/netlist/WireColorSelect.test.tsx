import { screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { renderWithProviders } from "../../../test/render";
import { WireColorSelect } from "./WireColorSelect";

function names(): (string | null)[] {
  const select = screen.getByRole("combobox");
  return within(select)
    .getAllByRole("option")
    .map((option) => option.textContent);
}

describe("WireColorSelect", () => {
  it("lists the colours by name, pink among them, after no colour", () => {
    renderWithProviders(<WireColorSelect label="Color" value={null} onChange={() => {}} />);

    expect(names()).toEqual([
      "No color",
      "Black",
      "Blue",
      "Brown",
      "Green",
      "Grey",
      "Orange",
      "Pink",
      "Red",
      "Violet",
      "White",
      "Yellow",
    ]);
  });

  it("orders them by their names in Portuguese too, not by the English ones", () => {
    renderWithProviders(<WireColorSelect label="Cor" value={null} onChange={() => {}} />, {
      language: "pt-BR",
    });

    expect(names()).toEqual([
      "Sem cor",
      "Amarelo",
      "Azul",
      "Branco",
      "Cinza",
      "Laranja",
      "Marrom",
      "Preto",
      "Rosa",
      "Verde",
      "Vermelho",
      "Violeta",
    ]);
  });
});
