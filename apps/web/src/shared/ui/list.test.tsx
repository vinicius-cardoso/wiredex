import { render } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { TableFrame } from "./list";

function frameOf(container: HTMLElement): HTMLElement {
  return container.firstElementChild as HTMLElement;
}

/** Puts the frame's top where a scrolled page would have it, and spies on scrollIntoView. */
function placeAt(frame: HTMLElement, top: number) {
  vi.spyOn(frame, "getBoundingClientRect").mockReturnValue({ top } as DOMRect);
  const scrollIntoView = vi.fn();
  frame.scrollIntoView = scrollIntoView;
  return scrollIntoView;
}

describe("TableFrame", () => {
  it("leaves the scroll alone on the first render", () => {
    const { container } = render(<TableFrame scrollKey="1:50">rows</TableFrame>);
    const frame = frameOf(container);

    expect(frame.scrollTop).toBe(0);
    expect(frame).toHaveTextContent("rows");
  });

  it("goes back to its first row when the page changes", () => {
    const { container, rerender } = render(<TableFrame scrollKey="1:50">rows</TableFrame>);
    const frame = frameOf(container);
    const scrollIntoView = placeAt(frame, 120);
    frame.scrollTop = 400;

    rerender(<TableFrame scrollKey="1:50">rows</TableFrame>);
    expect(frame.scrollTop).toBe(400);

    rerender(<TableFrame scrollKey="2:50">rows</TableFrame>);
    expect(frame.scrollTop).toBe(0);
    // Its start is on screen, so the page doesn't move.
    expect(scrollIntoView).not.toHaveBeenCalled();
  });

  it("brings the list's start into view when the page had scrolled past it", () => {
    const { container, rerender } = render(<TableFrame scrollKey="1:50">rows</TableFrame>);
    const frame = frameOf(container);
    const scrollIntoView = placeAt(frame, -300);

    rerender(<TableFrame scrollKey="1:25">rows</TableFrame>);

    expect(scrollIntoView).toHaveBeenCalledOnce();
    expect(scrollIntoView).toHaveBeenCalledWith({ block: "start" });
  });

  it("measures from the top of the area that scrolls it, as main does on a laptop", () => {
    const { container, rerender } = render(
      <div style={{ overflowY: "auto" }}>
        <TableFrame scrollKey="1:50">rows</TableFrame>
      </div>,
    );
    const main = container.firstElementChild as HTMLElement;
    Object.defineProperty(main, "scrollHeight", { value: 2000 });
    Object.defineProperty(main, "clientHeight", { value: 700 });
    vi.spyOn(main, "getBoundingClientRect").mockReturnValue({ top: 80 } as DOMRect);
    // Inside the viewport, but above main's top: scrolled up under the header.
    const scrollIntoView = placeAt(frameOf(main), 40);

    rerender(
      <div style={{ overflowY: "auto" }}>
        <TableFrame scrollKey="2:50">rows</TableFrame>
      </div>,
    );

    expect(scrollIntoView).toHaveBeenCalledOnce();
  });

  it("doesn't scroll without a page to follow", () => {
    const { container, rerender } = render(<TableFrame>rows</TableFrame>);
    const frame = frameOf(container);
    const scrollIntoView = placeAt(frame, -300);
    frame.scrollTop = 400;

    rerender(<TableFrame>other rows</TableFrame>);

    expect(frame.scrollTop).toBe(400);
    expect(scrollIntoView).not.toHaveBeenCalled();
  });
});
