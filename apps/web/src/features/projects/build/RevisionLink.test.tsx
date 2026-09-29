import { screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { createTestQueryClient, renderInRouter } from "../../../test/render";
import { aRevisionRef, respondWithRevisionRef } from "../../../test/server";
import { RevisionLink, RevisionRefLink } from "./RevisionLink";

const ref = aRevisionRef({
  id: "0199eeee-0000-7000-8000-00000000000a",
  label: "A",
  summary: "breadboard",
  project_id: "0199eeee-0000-7000-8000-000000000001",
  project_name: "Weather station",
});

describe("RevisionLink", () => {
  it("names a revision by its project and label, linking to it, from a ref it holds", async () => {
    renderInRouter(<RevisionRefLink revision={ref} />);

    const link = await screen.findByRole("link", { name: "Weather station · A – breadboard" });
    expect(link).toHaveAttribute("href", `/projects/${ref.project_id}/revisions/${ref.id}`);
  });

  it("uses just the label when the revision has no summary", async () => {
    renderInRouter(<RevisionRefLink revision={aRevisionRef({ ...ref, summary: null })} />);

    expect(await screen.findByRole("link", { name: "Weather station · A" })).toBeInTheDocument();
  });

  it("resolves an id to its ref through useRevisionRef", async () => {
    respondWithRevisionRef(ref);
    renderInRouter(<RevisionLink id={ref.id} />, { queryClient: createTestQueryClient() });

    expect(
      await screen.findByRole("link", { name: "Weather station · A – breadboard" }),
    ).toBeInTheDocument();
  });
});
