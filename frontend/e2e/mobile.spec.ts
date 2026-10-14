import { expect, test } from "@playwright/test";

import { signUpWithWorkspace } from "./helpers";

test.use({ viewport: { width: 390, height: 844 } });

test("the sidebar becomes a menu on small screens", async ({ page }) => {
  const basePath = await signUpWithWorkspace(page, "Mobile Co");
  await page.goto(basePath);

  const nav = page.getByRole("navigation", { name: "Main" });
  await expect(nav).not.toBeInViewport();

  await page.getByRole("button", { name: "Open menu" }).click();
  await expect(nav).toBeInViewport();
  await nav.getByRole("link", { name: "Runs", exact: true }).click();

  // Navigating closes the menu again.
  await expect(page.getByRole("heading", { name: "Runs", exact: true })).toBeVisible();
  await expect(nav).not.toBeInViewport();

  // No page in the app should scroll sideways on a phone.
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth - window.innerWidth,
  );
  expect(overflow).toBeLessThanOrEqual(1);
});
