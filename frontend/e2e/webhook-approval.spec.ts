import { expect, test } from "@playwright/test";

import { createFromTemplate, signUpWithWorkspace, uniqueEmail, waitForEmail } from "./helpers";

// Two background runs plus two email round trips through the worker and Mailpit.
test.setTimeout(120_000);

test("webhook run pauses for approval and finishes after the manager approves by email", async ({
  page,
  request,
}) => {
  const basePath = await signUpWithWorkspace(page, "Approval Co");
  await createFromTemplate(page, basePath, "Support ticket triage");
  const workflowId = new URL(page.url()).pathname.split("/").pop()!;

  // Publishing a webhook workflow reveals its secret exactly once.
  await page.getByRole("button", { name: "Publish" }).click();
  await page.getByLabel("What changed? (optional)").fill("First version");
  await page.getByRole("dialog").getByRole("button", { name: "Publish" }).click();
  const secretDialog = page.getByRole("dialog", { name: "Webhook secret" });
  await expect(secretDialog).toBeVisible();
  const secret = (await secretDialog.locator("code").first().textContent())!.trim();
  expect(secret.length).toBeGreaterThan(20);
  await secretDialog.getByRole("button", { name: "Done" }).click();
  await expect(page.getByText("Active · v1")).toBeVisible();

  // Wrong secret is rejected; the same Idempotency-Key starts only one run.
  const hook = `/api/v1/hooks/${workflowId}`;
  const denied = await request.post(hook, {
    headers: { "X-FlowForge-Secret": "wrong" },
    data: { message: "refund please" },
  });
  expect(denied.status()).toBe(401);

  const customer = uniqueEmail("refund");
  const send = () =>
    request.post(hook, {
      headers: { "X-FlowForge-Secret": secret, "Idempotency-Key": `order-${customer}` },
      data: { email: customer, message: "Please refund my order, it arrived broken" },
    });
  const first = await send();
  expect(first.status()).toBe(202);
  const second = await send();
  expect(second.status()).toBe(200);
  expect(((await second.json()) as { duplicate: boolean }).duplicate).toBe(true);

  // The run waits in the approvals inbox.
  await page.goto(`${basePath}/approvals`);
  await expect(page.getByText(`Refund request from ${customer}`)).toBeVisible({ timeout: 30_000 });

  // The approver follows the link from the email.
  const text = await waitForEmail(request, `"${customer}" subject:"Approval needed"`);
  const link = /\/approvals\/[A-Za-z0-9_-]+/.exec(text);
  expect(link).not.toBeNull();
  await page.goto(link![0]);
  await page.getByLabel("Your name").fill("Morgan Manager");
  await page.getByRole("button", { name: "Approve" }).click();
  await expect(page.getByText("The workflow has continued")).toBeVisible();

  await waitForEmail(request, `to:${customer} subject:"Your refund is approved"`);

  await page.goto(`${basePath}/runs`);
  const row = page.getByRole("row", { name: /Support ticket triage/ });
  await expect(row).toHaveCount(1);
  await expect(row.getByText("succeeded")).toBeVisible({ timeout: 30_000 });
});
