import { expect, type APIRequestContext, type Page } from "@playwright/test";

export const PASSWORD = "e2e-password-123";
export const MAILPIT_URL = process.env.E2E_MAILPIT_URL ?? "http://localhost:8025";

export function uniqueEmail(prefix: string): string {
  // Reserved TLDs such as .test are rejected by the backend's email validation.
  return `${prefix}-${Date.now()}-${Math.floor(Math.random() * 1e6)}@example.com`;
}

/** Register a new account and create a workspace. Returns the workspace base path. */
export async function signUpWithWorkspace(page: Page, workspaceName: string): Promise<string> {
  await page.goto("/register");
  await page.getByLabel("Full name").fill("E2E Owner");
  await page.getByLabel("Work email").fill(uniqueEmail("owner"));
  await page.getByLabel("Password").fill(PASSWORD);
  await page.getByRole("button", { name: "Create account" }).click();

  await expect(page).toHaveURL(/\/app\/new/);
  await page.getByLabel("Company name").fill(workspaceName);
  await page.getByRole("button", { name: "Create workspace" }).click();
  await expect(page).toHaveURL(/\/workflows\?onboarding=1/);
  return new URL(page.url()).pathname.replace(/\/workflows$/, "");
}

/** Create a workflow from a gallery template and wait for the editor. */
export async function createFromTemplate(page: Page, basePath: string, templateName: string) {
  await page.goto(`${basePath}/workflows`);
  await page.getByRole("button", { name: "New workflow" }).first().click();
  await page.getByRole("button", { name: new RegExp(templateName) }).click();
  await page.getByRole("button", { name: "Create workflow" }).click();
  await expect(page).toHaveURL(/\/workflows\/[0-9a-f-]{36}$/);
  await expect(page.getByLabel("Workflow name")).toHaveValue(templateName);
}

interface MailpitSummary {
  ID: string;
  Subject: string;
}

/** Poll Mailpit until a message matching the search query arrives; returns its plain text. */
export async function waitForEmail(request: APIRequestContext, query: string): Promise<string> {
  let found: MailpitSummary | undefined;
  await expect
    .poll(
      async () => {
        const response = await request.get(`${MAILPIT_URL}/api/v1/search`, {
          params: { query },
        });
        const body = (await response.json()) as { messages: MailpitSummary[] };
        found = body.messages[0];
        return Boolean(found);
      },
      { timeout: 30_000, message: `email matching ${query}` },
    )
    .toBe(true);
  const message = await request.get(`${MAILPIT_URL}/api/v1/message/${found!.ID}`);
  return ((await message.json()) as { Text: string }).Text;
}
