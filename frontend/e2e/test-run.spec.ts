import { expect, test } from "@playwright/test";

import { createFromTemplate, signUpWithWorkspace, waitForEmail, uniqueEmail } from "./helpers";

test("a test run of a template executes the bug branch and skips the others", async ({
  page,
  request,
}) => {
  const basePath = await signUpWithWorkspace(page, "Test Run Co");
  await createFromTemplate(page, basePath, "Support ticket triage");

  const customer = uniqueEmail("customer");
  await page.getByRole("button", { name: "Test run", exact: true }).click();
  await page.getByLabel("Trigger payload (JSON)").fill(
    JSON.stringify({
      body: { email: customer, message: "There is a bug: the export button crashes the app" },
      query: {},
      headers: {},
    }),
  );
  await page.getByRole("button", { name: "Run", exact: true }).click();

  // Each row in the run panel reads "<status> <node id> [→ branch] <duration>".
  await expect(page.getByRole("link", { name: "Open run details" })).toBeVisible();
  await expect(page.getByRole("button", { name: /^succeeded notify_engineering/ })).toBeVisible({
    timeout: 30_000,
  });
  await expect(page.getByRole("button", { name: /^succeeded classify → bug/ })).toBeVisible();
  await expect(page.getByRole("button", { name: /^skipped send_reply/ })).toBeVisible();

  const text = await waitForEmail(request, `subject:"Bug report from ${customer}"`);
  expect(text).toContain("export button");

  await page.getByRole("link", { name: "Open run details" }).click();
  await expect(page.getByRole("heading", { name: "Timeline" })).toBeVisible();
  await expect(page.getByText("succeeded").first()).toBeVisible();
  await expect(page.getByRole("button", { name: "skipped draft_reply" })).toBeVisible();
});

test("the editor saves renames and keeps them after a reload", async ({ page }) => {
  const basePath = await signUpWithWorkspace(page, "Rename Co");
  await createFromTemplate(page, basePath, "Daily news digest");

  const name = page.getByLabel("Workflow name");
  await name.fill("Morning digest");
  await expect(page.getByText("Unsaved changes")).toBeVisible();
  await page.keyboard.press("Control+s");
  await expect(page.getByText("All changes saved")).toBeVisible();

  await page.reload();
  await expect(page.getByLabel("Workflow name")).toHaveValue("Morning digest");
});
