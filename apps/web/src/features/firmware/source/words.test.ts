import { describe, expect, it } from "vitest";
import { changedSpans, marked } from "./words";

describe("changedSpans", () => {
  it("finds the words each side has alone", () => {
    const before = "  for (uint8_t count = 1; count <= 3; count++) {";
    const after = "  for (uint8_t count = 1; count <= MAX_BLINKS; count++) {";
    const spans = changedSpans(before, after);
    expect(spans?.old.map(([start, end]) => before.slice(start, end))).toEqual(["3"]);
    expect(spans?.new.map(([start, end]) => after.slice(start, end))).toEqual(["MAX_BLINKS"]);
  });

  it("marks nothing on one side when words were only added", () => {
    expect(changedSpans("delay(100);", "delay(100); // slower")).toEqual({
      old: [],
      new: [[11, 21]],
    });
  });

  it("gives up on two lines with little in common, and on a very long one", () => {
    expect(changedSpans("pinMode(LED_PIN, OUTPUT);", "Serial.begin(115200);")).toBeNull();
    expect(changedSpans("a".repeat(501), "a".repeat(501))).toBeNull();
  });
});

describe("marked", () => {
  const tokens = [
    { text: "const", classes: "tok-keyword" },
    { text: " LED = ", classes: "" },
    { text: "13", classes: "tok-number" },
    { text: ";", classes: "" },
  ];

  it("leaves the tokens alone without spans", () => {
    expect(marked(tokens, [], "word")).toBe(tokens);
  });

  it("adds the class to a whole token and keeps its own", () => {
    expect(marked(tokens, [[12, 14]], "word")).toEqual([
      tokens[0],
      tokens[1],
      { text: "13", classes: "tok-number word" },
      tokens[3],
    ]);
  });

  it("splits a token a span starts or ends inside, and follows a span across tokens", () => {
    const result = marked(
      tokens,
      [
        [2, 4],
        [6, 13],
      ],
      "word",
    );
    expect(result).toEqual([
      { text: "co", classes: "tok-keyword" },
      { text: "ns", classes: "tok-keyword word" },
      { text: "t", classes: "tok-keyword" },
      { text: " ", classes: "" },
      { text: "LED = ", classes: "word" },
      { text: "1", classes: "tok-number word" },
      { text: "3", classes: "tok-number" },
      { text: ";", classes: "" },
    ]);
    expect(result.map((token) => token.text).join("")).toBe("const LED = 13;");
  });
});
