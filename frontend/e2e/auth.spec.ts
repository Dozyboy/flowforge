import { expect, test } from "@playwright/test";

import { PASSWORD, uniqueEmail } from "./helpers";

test("sign up, create a workspace, sign out and sign back in", async ({ page }) => {
  const email = uniqueEmail("auth");

  await page.goto("/register");
  await page.getByLabel("Full name").fill("Avery Ops");
  await page.getByLabel("Work email").fill(email);
  await page.getByLabel("Password").fill(PASSWORD);
  await page.getByRole("button", { name: "Create account" }).click();

  await expect(page).toHaveURL(/\/app\/new/);
  await page.getByLabel("Company name").fill("Avery Logistics");
  await page.getByRole("button", { name: "Create workspace" }).click();

  await expect(page).toHaveURL(/\/workflows\?onboarding=1/);
  await expect(page.getByText("Welcome to FlowForge!")).toBeVisible();
  await expect(page.getByText("No workflows yet")).toBeVisible();

  await page.getByRole("button", { name: "Sign out" }).click();
  await expect(page).toHaveURL(/\/login/);

  await page.getByLabel("Email").fill(email);
  await page.getByLabel("Password").fill(PASSWORD);
  await page.getByRole("button", { name: "Sign in" }).click();
  // Signing in returns to the page the session ended on.
  await expect(page.getByRole("heading", { name: "Workflows", exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "Avery Logistics" })).toBeVisible();
});

test("protected pages redirect to sign in", async ({ page }) => {
  await page.goto("/app");
  await expect(page).toHaveURL(/\/login/);
});
