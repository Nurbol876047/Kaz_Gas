import { test, expect } from "@playwright/test";
import { randomUUID } from "node:crypto";

test("registry, verified lookup, meter reading review and mobile layout", async ({ page, request }) => {
  const key = process.env.BOT_API_KEY;
  if (!key) throw new Error("BOT_API_KEY required for isolated test environment");
  const apiURL = process.env.E2E_API_URL || "http://127.0.0.1:8000/api";
  const headers = { "X-Bot-Key": key };
  const suffix = Date.now().toString();
  const number = `00${suffix}`;
  const meter = `QA-${suffix}`;
  const userId = Number(suffix);
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.goto("/login");
  await page.getByLabel("Email", { exact: true }).fill("e2e@example.com");
  await page.getByLabel("Құпиясөз", { exact: true }).fill("e2e-only-password-123");
  await page.getByRole("button", { name: "Кіру", exact: true }).click();
  await page.getByRole("link", { name: "Абоненттер", exact: true }).click();
  await page.getByRole("button", { name: "Абонент қосу" }).click();
  const dialog = page.getByRole("dialog");
  await dialog.getByLabel("Дербес шот", { exact: true }).fill(number);
  await dialog.getByLabel("Есептегіштің зауыттық нөмірі").fill(meter);
  await dialog.getByLabel("Аты-жөні", { exact: true }).fill("Synthetic Browser Resident");
  await dialog.getByLabel("Мекенжай", { exact: true }).fill("Synthetic test address 1");
  await dialog.getByRole("button", { name: "Сақтау", exact: true }).click();
  await expect(dialog).not.toBeVisible();
  await page.getByLabel("Абонентті іздеу").fill(number);
  await page.getByRole("button", { name: "Іздеу", exact: true }).click();
  const row = page.locator("tbody tr").filter({ hasText: number });
  await expect(row).toHaveCount(1);
  const unverified = await request.post(`${apiURL}/internal/subscribers/lookup`, { headers,
    data: { telegram_user_id: userId, identifier: number } });
  expect(await unverified.json()).toEqual({ verified: false });
  await row.getByRole("button", { name: "Қолжетімділік", exact: true }).click();
  await dialog.getByLabel(/^Telegram ID/).fill(String(userId));
  await dialog.getByLabel("Растау немесе жою негізі").fill("Synthetic browser identity check");
  await dialog.getByRole("button", { name: "Қолжетімділікті сақтау" }).click();
  await expect(dialog).not.toBeVisible();
  await expect(row).toContainText(String(userId));
  const verified = await request.post(`${apiURL}/internal/subscribers/lookup`, { headers,
    data: { telegram_user_id: userId, identifier: meter, kind: "meter" } });
  const result = await verified.json();
  expect(result.verified).toBe(true);
  expect(result.account.account_number).toBe(number);
  await page.screenshot({ path: "test-results/subscribers-desktop.png", fullPage: true });
  const parts = new Intl.DateTimeFormat("en", { timeZone: "Asia/Qyzylorda", year: "numeric", month: "2-digit" }).formatToParts();
  const period = `${parts.find((p) => p.type === "year")!.value}-${parts.find((p) => p.type === "month")!.value}-01`;
  const tinyJpeg = Buffer.from(
    "/9j/4AAQSkZJRgABAQEAYABgAAD/2wBDAAMCAgICAgMCAgIDAwMDBAYEBAQEBAgGBgUGCQgKCgkICQkKDA8MCgsOCwkJDRENDg8QEBEQCgwSExIQEw8QEBD/2wBDAQMDAwQDBAgEBAgQCwkLEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBAQEBD/wAARCAABAAEDASIAAhEBAxEB/8QAFQABAQAAAAAAAAAAAAAAAAAAAAj/xAAUEAEAAAAAAAAAAAAAAAAAAAAA/8QAFQEBAQAAAAAAAAAAAAAAAAAAAAX/xAAUEQEAAAAAAAAAAAAAAAAAAAAA/9oADAMBAAIRAxEAPwCdABmX/9k=",
    "base64",
  );
  const photo = await request.post(`${apiURL}/internal/photos`, { headers, multipart: {
    telegram_user_id: String(userId), telegram_file_id: `qa-${suffix}`, file_type: "METER_READING_PHOTO",
    photo: { name: "meter.jpg", mimeType: "image/jpeg", buffer: tinyJpeg },
  } });
  expect(photo.ok(), await photo.text()).toBeTruthy();
  const reading = await request.post(`${apiURL}/internal/subscribers/readings`, { headers, data: {
    telegram_user_id: userId, account_id: result.account.id, idempotency_key: randomUUID(),
    photo_id: (await photo.json()).id, period,
  } });
  expect(reading.ok(), await reading.text()).toBeTruthy();
  await page.getByRole("button", { name: "Газ көрсеткіштері", exact: true }).click();
  await row.getByRole("button", { name: "Тексеру", exact: true }).click();
  await dialog.getByLabel("Фотодан оқылған көрсеткіш (м³)").fill("100.125");
  await dialog.getByLabel("Түсініктеме", { exact: true }).fill("Initial reading checked");
  await dialog.getByRole("button", { name: "Шешімді сақтау" }).click();
  await expect(dialog).not.toBeVisible();
  await expect(row).toContainText("Қабылданды");
  const history = await request.get(`${apiURL}/internal/subscribers/${userId}/readings`, { headers });
  expect((await history.json()).items[0].status).toBe("ACCEPTED");
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(page.locator(".sidebar")).not.toBeInViewport();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await page.screenshot({ path: "test-results/subscribers-mobile.png", fullPage: true, animations: "disabled" });
  expect(errors).toEqual([]);
});
