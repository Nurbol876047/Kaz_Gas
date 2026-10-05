import { test, expect } from "@playwright/test";
import { randomUUID } from "node:crypto";
const apiURL = process.env.E2E_API_URL || "http://127.0.0.1:8000/api";
const botKey = process.env.BOT_API_KEY;
test("login, real application, realtime, status, reports, settings and responsive layout", async ({
  page,
  request,
}) => {
  if (!botKey)
    throw new Error("BOT_API_KEY required for service API integration test");
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.goto("/login");
  await expect(
    page.getByRole("heading", { name: "Қош келдіңіз" }),
  ).toBeVisible();
  await page.getByLabel("Email", { exact: true }).fill("e2e@example.com");
  await page
    .getByLabel("Құпиясөз", { exact: true })
    .fill("e2e-only-password-123");
  await page.getByRole("button", { name: "Кіру", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "Бақылау тақтасы" }),
  ).toBeVisible();
  await expect(page.getByText("Тікелей", { exact: true })).toBeVisible();
  const resident = Math.floor(Date.now() / 1000);
  const personalAccount = String(resident) + "01";
  const auth = await (await page.request.get("/api/auth/me")).json();
  const registryHeaders = { "X-CSRF-Token": auth.csrf_token, Origin: new URL(page.url()).origin };
  const registered = await page.request.post("/api/subscribers", {
    headers: registryHeaders,
    data: { account_number: personalAccount, meter_number: `E2E-${resident}`, full_name: "E2E resident",
      address: "Synthetic test address", phone: null },
  });
  expect(registered.ok(), await registered.text()).toBeTruthy();
  const subscriber = await registered.json();
  const bound = await page.request.post(`/api/subscribers/${subscriber.id}/binding`, {
    headers: registryHeaders,
    data: { telegram_user_id: resident, version: subscriber.version, reason: "Synthetic E2E verification" },
  });
  expect(bound.ok(), await bound.text()).toBeTruthy();
  const date = new Date(Date.now() + 86400000).toISOString().slice(0, 10);
  const created = await request.post(`${apiURL}/internal/applications`, {
    headers: { "X-Bot-Key": botKey },
    data: {
      user: { telegram_user_id: resident, first_name: "E2E resident" },
      idempotency_key: randomUUID(),
      personal_account: personalAccount,
      application_type: "MPI_REMOVAL",
      requested_date: date,
    },
  });
  expect(created.ok(), await created.text()).toBeTruthy();
  const application = await created.json();
  await expect(page.locator(".toast")).toContainText(
    application.application_number,
  );
  await page.goto(`/applications/${application.id}`);
  await expect(
    page.getByRole("heading", {
      name: application.application_number,
      exact: true,
    }),
  ).toBeVisible();
  await page
    .getByRole("combobox", { name: "Жаңа мәртебе" })
    .selectOption("IN_PROGRESS");
  await page.getByRole("button", { name: "Мәртебені өзгерту" }).click();
  await expect(page.locator(".detail-badges")).toContainText("Өңделуде");
  await page.locator("#note").fill("E2E internal comment");
  await page.getByRole("button", { name: "Қосу", exact: true }).click();
  await expect(page.locator(".timeline")).toContainText("E2E internal comment");
  await page
    .getByRole("combobox", { name: "Жаңа мәртебе" })
    .selectOption("COMPLETED");
  await page.getByRole("button", { name: "Мәртебені өзгерту" }).click();
  await expect(page.locator(".detail-badges")).toContainText("Аяқталды");
  await page.goto("/applications");
  await page.getByLabel("Өтінім іздеу").fill(application.application_number);
  await expect(page.locator("tbody tr")).toHaveCount(1);
  await expect(page.locator("tbody")).toContainText(
    application.application_number,
  );
  await page.setViewportSize({ width: 390, height: 844 });
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBe(true);
  await page.setViewportSize({ width: 1280, height: 900 });
  await page.goto("/reports");
  const download = page.waitForEvent("download");
  await page.getByRole("button", { name: "Excel", exact: true }).click();
  expect((await download).suggestedFilename()).toBe("applications.xlsx");
  await page.goto("/settings");
  await expect(page.getByLabel("Ұйым атауы", { exact: true })).toBeVisible();
  await page.getByLabel("Ұйым атауы", { exact: true }).fill("Qala Gas E2E");
  await page.getByRole("button", { name: "Өзгерістерді сақтау" }).click();
  await expect(page.getByRole("status")).toContainText("Баптаулар сақталды");
  await page.goto("/");
  await expect(
    page.getByRole("heading", { name: "Бақылау тақтасы" }),
  ).toBeVisible();
  await page.screenshot({
    path: "test-results/dashboard-desktop.png",
    fullPage: true,
  });
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(page.getByRole("button", { name: "Мәзірді ашу" })).toBeVisible();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBe(true);
  await page.screenshot({
    path: "test-results/dashboard-mobile.png",
    fullPage: true,
  });
  await page.getByRole("button", { name: "Мәзірді ашу" }).click();
  await expect(page.locator(".sidebar")).toHaveClass(/is-open/);
  expect(errors).toEqual([]);
});
