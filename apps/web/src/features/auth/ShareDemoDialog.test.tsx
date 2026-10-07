import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { HttpResponse, http } from "msw";
import { describe, expect, it } from "vitest";
import { renderInRouter } from "../../test/render";
import { OWNER, server } from "../../test/server";
import { UserMenu } from "./UserMenu";

const SHARED = {
  email: "friend@example.com",
  name: "Friend",
  password: "a made up password",
  expires_at: "2026-10-21T15:30:00Z",
};

/** Answers the invitation with SHARED, or with STATUS, and holds every body sent. */
function acceptShares(status = 201): unknown[] {
  const sent: unknown[] = [];
  server.use(
    http.post("*/api/auth/guests", async ({ request }) => {
      sent.push(await request.json());
      return status === 201
        ? HttpResponse.json(SHARED, { status })
        : HttpResponse.json({ detail: "refused" }, { status });
    }),
  );
  return sent;
}

async function openDialog(user = OWNER) {
  renderInRouter(<UserMenu user={user} />);
  const actor = userEvent.setup();
  await actor.click(await screen.findByRole("button", { name: `Account of ${user.name}` }));
  await actor.click(screen.getByRole("menuitem", { name: "Share a demo" }));
  return { actor, dialog: screen.getByRole("dialog", { name: "Share a demo" }) };
}

describe("sharing a demo from the account menu", () => {
  it("isn't offered to a guest, who can't invite", async () => {
    renderInRouter(<UserMenu user={{ ...OWNER, expires_at: "2026-10-21T15:30:00Z" }} />);
    await userEvent.setup().click(await screen.findByRole("button", { name: /^Account of/ }));
    expect(screen.getByRole("menuitem", { name: "Log out" })).toBeVisible();
    expect(screen.queryByRole("menuitem", { name: "Share a demo" })).toBeNull();
  });

  it("asks for an email, a name and the days, a week unless told otherwise", async () => {
    const sent = acceptShares();
    const { actor, dialog } = await openDialog();
    expect(screen.queryByRole("menu")).toBeNull();
    expect(dialog).toHaveTextContent("They see nothing of yours, and you see nothing of theirs.");
    const email = within(dialog).getByRole("textbox", { name: "Email" });
    expect(email).toHaveFocus();
    expect(within(dialog).getByRole("spinbutton", { name: "Access for (days)" })).toHaveValue(7);

    await actor.type(email, "friend@example.com");
    await actor.click(within(dialog).getByRole("button", { name: "Create the guest account" }));

    await expect.poll(() => sent).toEqual([{ email: "friend@example.com", name: null, days: 7 }]);
  });

  it("shows the guest's login once it is made, the password included, and copies it", async () => {
    const sent = acceptShares();
    const { actor, dialog } = await openDialog();
    await actor.type(
      within(dialog).getByRole("textbox", { name: "Email" }),
      " friend@example.com ",
    );
    await actor.type(within(dialog).getByRole("textbox", { name: "Name" }), "Friend");
    const days = within(dialog).getByRole("spinbutton", { name: "Access for (days)" });
    await actor.clear(days);
    await actor.type(days, "30");
    await actor.keyboard("{Enter}");

    const done = await screen.findByRole("dialog", { name: "Friend can log in" });
    expect(sent).toEqual([{ email: "friend@example.com", name: "Friend", days: 30 }]);
    expect(done).toHaveTextContent("Nothing was emailed.");
    expect(done).toHaveTextContent("a made up password");
    expect(done).toHaveTextContent("friend@example.com");
    expect(done).toHaveTextContent(/Works until.*October 21, 2026/);
    expect(done).toHaveTextContent("The password is shown only now.");

    await actor.click(within(done).getByRole("button", { name: "Copy the login" }));
    expect(await within(done).findByText("Copied.")).toBeVisible();
    const copied = await navigator.clipboard.readText();
    expect(copied).toContain("Email: friend@example.com");
    expect(copied).toContain("Password: a made up password");
    expect(copied).toContain(`Address: ${window.location.origin}`);

    await actor.click(within(done).getByRole("button", { name: "Close" }));
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it.each([
    [409, "That email already has an account. Use another."],
    [422, "Check the email and the number of days."],
    [500, "The guest account couldn't be created. Try again in a moment."],
  ])("says why when the API answers %i, and keeps what was typed", async (status, message) => {
    acceptShares(status);
    const { actor, dialog } = await openDialog();
    const email = within(dialog).getByRole("textbox", { name: "Email" });
    await actor.type(email, "friend@example.com");
    await actor.keyboard("{Enter}");

    expect(await within(dialog).findByRole("alert")).toHaveTextContent(message);
    expect(email).toHaveValue("friend@example.com");
    expect(email).toHaveAccessibleDescription(message);
  });

  it("closes on Cancel without asking the API", async () => {
    const sent = acceptShares();
    const { actor, dialog } = await openDialog();
    await actor.click(within(dialog).getByRole("button", { name: "Cancel" }));
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(sent).toEqual([]);
  });

  it("speaks Brazilian Portuguese", async () => {
    renderInRouter(<UserMenu user={OWNER} />, { language: "pt-BR" });
    const actor = userEvent.setup();
    await actor.click(await screen.findByRole("button", { name: /^Conta de/ }));
    await actor.click(screen.getByRole("menuitem", { name: "Compartilhar uma demo" }));
    expect(screen.getByRole("dialog", { name: "Compartilhar uma demo" })).toHaveTextContent(
      "Acesso por (dias)",
    );
  });
});
