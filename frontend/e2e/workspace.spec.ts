import { expect, test } from "@playwright/test";

import { signUpWithWorkspace, uniqueEmail } from "./helpers";

test("credentials are stored without ever showing the secret again", async ({ page }) => {
  const basePath = await signUpWithWorkspace(page, "Vault Co");
  await page.goto(`${basePath}/credentials`);
  await expect(page.getByText("No credentials yet")).toBeVisible();

  await page.getByRole("button", { name: "New credential" }).click();
  await page.getByLabel("Name", { exact: true }).fill("CRM token");
  await page.getByLabel("Type").selectOption({ label: "Bearer token" });
  await page.getByLabel("Token").fill("super-secret-token-value");
  await page.getByRole("button", { name: "Save" }).click();

  await expect(page.getByText("CRM token")).toBeVisible();
  await expect(page.getByText("super-secret-token-value")).toHaveCount(0);

  await page.getByRole("button", { name: "Edit" }).click();
  await expect(page.getByText("Saved secrets are never shown")).toBeVisible();
  await expect(page.getByRole("textbox", { name: "Token" })).toHaveValue("");
});

test("owners invite teammates and see plan usage and the audit log", async ({ page }) => {
  const basePath = await signUpWithWorkspace(page, "Team Co");

  await page.goto(`${basePath}/settings/members`);
  const invitee = uniqueEmail("teammate");
  await page.getByLabel("Email address").fill(invitee);
  await page.getByRole("button", { name: "Send invite" }).click();
  await expect(page.getByText(invitee, { exact: true })).toBeVisible();

  await page.goto(`${basePath}/settings/usage`);
  await expect(page.getByText("Runs this month")).toBeVisible();
  await expect(page.getByRole("main").getByText("Workflows", { exact: true })).toBeVisible();

  await page.goto(`${basePath}/settings/audit-log`);
  await expect(page.getByText("member.invited")).toBeVisible();
});
