import { createMemoryHistory, RouterProvider } from "@tanstack/react-router";
import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { createAppRouter } from "../../app/router";
import { createTestQueryClient, renderWithProviders } from "../../test/render";
import {
  acceptPasswordChanges,
  aSession,
  respondAsLoggedIn,
  respondWithApiVersion,
} from "../../test/server";

const OLD = "correct horse battery";
const NEW = "a brand new passphrase";
const phone = aSession({
  id: "0199aaaa-0000-7000-8000-0000000000b2",
  device: "Wiredex-Mobile/1.0",
  current: false,
});

async function renderForm(...options: Parameters<typeof acceptPasswordChanges>) {
  respondWithApiVersion("0.0.0");
  respondAsLoggedIn();
  const sent = acceptPasswordChanges(...options);
  const queryClient = createTestQueryClient();
  const history = createMemoryHistory({ initialEntries: ["/sessions"] });
  renderWithProviders(<RouterProvider router={createAppRouter(queryClient, history)} />, {
    queryClient,
  });
  const form = within(await screen.findByRole("form", { name: "Change your password" }));
  const fields = {
    current: form.getByLabelText("Current password"),
    next: form.getByLabelText("New password"),
    confirm: form.getByLabelText("New password, again"),
  };
  const save = form.getByRole("button", { name: "Change password" });
  return { sent, form, ...fields, save, user: userEvent.setup() };
}

describe("ChangePasswordForm", () => {
  it("changes the password, says who was logged out and clears the fields", async () => {
    const { sent, form, current, next, confirm, save, user } = await renderForm([
      aSession(),
      phone,
    ]);
    expect(await screen.findAllByRole("listitem")).toHaveLength(2);

    await user.type(current, OLD);
    await user.type(next, NEW);
    await user.type(confirm, NEW);
    await user.click(save);

    expect(await form.findByRole("status")).toHaveTextContent(
      "Your password is changed. 1 other device was logged out.",
    );
    expect(sent).toEqual([{ current_password: OLD, new_password: NEW }]);
    for (const field of [current, next, confirm]) expect(field).toHaveValue("");
    // The list is read again: only this device is left.
    expect(await screen.findAllByRole("listitem")).toHaveLength(1);
  });

  it("hides what is typed, tells a password manager what each field is, and can show it", async () => {
    const { form, current, next, confirm, user } = await renderForm();

    expect(current).toHaveAttribute("type", "password");
    expect(current).toHaveAttribute("autocomplete", "current-password");
    expect(next).toHaveAttribute("autocomplete", "new-password");
    expect(confirm).toHaveAttribute("autocomplete", "new-password");
    expect(next).toHaveAccessibleDescription(/At least 12 characters/);

    await user.click(form.getByRole("checkbox", { name: "Show the passwords" }));
    for (const field of [current, next, confirm]) expect(field).toHaveAttribute("type", "text");
  });

  it.each([
    ["", NEW, NEW, "Type your current password."],
    [OLD, "too short", "too short", "The new password needs at least 12 characters."],
    [OLD, OLD, OLD, "The new password is the current one. Choose a different one."],
    [OLD, NEW, `${NEW}!`, "The two new passwords aren't the same. Type the new password again."],
  ])("asks nothing of the API when the form itself is wrong", async (old, next, again, message) => {
    const form = await renderForm();

    if (old) await form.user.type(form.current, old);
    await form.user.type(form.next, next);
    await form.user.type(form.confirm, again);
    await form.user.click(form.save);

    expect(form.form.getByRole("alert")).toHaveTextContent(message);
    expect(form.sent).toEqual([]);
  });

  it("marks a wrong current password, clears it and keeps the new one", async () => {
    const { form, current, next, confirm, save, user } = await renderForm();

    await user.type(current, "not the password");
    await user.type(next, NEW);
    await user.type(confirm, NEW);
    await user.click(save);

    expect(await form.findByRole("alert")).toHaveTextContent(
      "That isn't your current password. Nothing was changed.",
    );
    expect(current).toHaveAttribute("aria-invalid", "true");
    expect(current).toHaveValue("");
    expect(current).toHaveFocus();
    expect(next).toHaveValue(NEW);
    expect(form.queryByRole("status")).not.toBeInTheDocument();
  });

  it.each([
    [{ status: 422, code: "password_like_account" }, /can't be or contain your email or your name/],
    [{ status: 429 }, /Too many wrong tries\. Nothing was changed; wait about 15 minutes/],
    [{ status: 500 }, /couldn't be changed right now\. Nothing was changed/],
  ])("says why the API refused, and that nothing changed", async (refuse, message) => {
    const { form, current, next, confirm, save, user } = await renderForm([aSession()], refuse);

    await user.type(current, OLD);
    await user.type(next, NEW);
    await user.type(confirm, NEW);
    await user.click(save);

    expect(await form.findByRole("alert")).toHaveTextContent(message);
    expect(form.queryByRole("status")).not.toBeInTheDocument();
  });
});
