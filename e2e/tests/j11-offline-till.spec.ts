import { closeOpenTills, seedCatalogue } from "../lib/seed";
import { expect, shared, signIn, signedInApi, test } from "../lib/test";
import { lbl } from "../lib/ui";

// J11: the till keeps selling with no connection. Two sales are made offline (one found by scanning a barcode), the page
// is reloaded offline (the app loads from the service worker, the cart and the queue survive), a sale is held offline,
// then the connection returns: both sales reach the server once with the right totals, the held sale is uploaded, and a
// sale whose answer is lost on the way is still only one sale. Also: server-side hold and resume while online.
test("J11 sell without a connection, then reconnect", async ({ page, context, problems }) => {
  const s = shared();
  const api = await signedInApi(s.owner);
  await closeOpenTills(api);
  const cat = await seedCatalogue(api, [{ name: "Rope", price: 10, cost: 6, qty: 50 }, { name: "Glue", price: 4, cost: 2, qty: 30 }]);
  const [rope, glue] = cat.products;
  const barcode = `5${Date.now()}`.slice(0, 13);

  // --- the barcode is added on the product's page
  await signIn(page, s.owner);
  await page.goto(`/products/${rope.id}`);
  await page.getByRole("button", { name: "Edit barcodes" }).click();
  await page.getByLabel("Codes", { exact: true }).fill(barcode);
  await page.getByRole("button", { name: "Save barcodes" }).click();
  await expect(page.getByText("Barcodes saved")).toBeVisible();
  await expect(page.getByRole("list", { name: "Barcodes" }).getByText(barcode)).toBeVisible();
  expect((await api.get<any>(`/products/products/${rope.id}`)).barcodes).toEqual([barcode]);

  // --- online: open the till; let the app save its shell and the copy of prices on this device
  await page.goto("/pos/terminal");
  await page.getByLabel(lbl("Till (device)")).selectOption(cat.deviceId);
  await page.getByLabel(lbl("Opening float")).fill("100");
  await page.getByRole("button", { name: "Open till and start selling" }).click();
  const search = page.getByLabel("Search or scan: name, SKU or barcode");
  await expect(search).toBeVisible();
  const chip = page.getByTestId("sync-chip");
  await expect(chip).toHaveAttribute("data-state", "online");
  await page.evaluate(() => navigator.serviceWorker.ready.then(() => undefined));
  await page.waitForFunction(() => !!navigator.serviceWorker.controller);
  await expect.poll(() => savedCopy(page), { message: "the copy of prices is saved on this device", timeout: 30_000 }).toBeGreaterThanOrEqual(2);
  const till = (await api.get<any[]>("/pos/tills?status=open"))[0];

  // --- no connection
  await context.setOffline(true);
  await expect(chip).toHaveAttribute("data-state", "offline");
  await expect(page.getByTestId("sync-banner")).toContainText("No connection");

  // sale A: found by scanning its barcode, two ropes, exact cash
  const madeA = Date.now();
  await search.fill(barcode);
  await search.press("Enter");
  await page.getByRole("button", { name: "One more" }).click();
  await expect(page.getByText("20.00").first()).toBeVisible();
  await page.getByRole("button", { name: /^Pay/ }).click();
  await expect(page.getByText(/No connection\. The sale will be saved on this device/)).toBeVisible();
  await expect(page.getByRole("button", { name: "On account" })).toHaveCount(0);       // no customer attached; account sales need a connection
  await page.getByRole("button", { name: "Save sale" }).click();
  await expect(page.getByText("Sale saved on this device")).toBeVisible();
  await expect(page.getByTestId("sale-number")).toHaveText(/^OFFLINE-.+-0001$/);
  await expect(page.getByText(/provisional/i).first()).toBeVisible();
  await page.getByRole("button", { name: "New sale" }).click();

  // sale B: one glue, 5 handed over for 4 (1 change)
  await search.fill(glue.sku);
  await search.press("Enter");
  await page.getByRole("button", { name: /^Pay/ }).click();
  await page.getByLabel(lbl("Handed over")).fill("5");
  await expect(page.getByText("1.00").first()).toBeVisible();
  await page.getByRole("button", { name: "Save sale" }).click();
  await expect(page.getByTestId("sale-number")).toHaveText(/-0002$/);
  await page.getByRole("button", { name: "New sale" }).click();
  await expect(chip).toContainText("2 waiting");

  // a half-finished sale survives a reload with no connection; the page itself loads from the service worker
  await search.fill(rope.sku);
  await search.press("Enter");
  await page.reload();
  await expect(page.getByLabel("Search or scan: name, SKU or barcode")).toBeVisible();
  await expect(page.getByText(rope.name).first()).toBeVisible();                       // the cart line is still there
  await expect(chip).toHaveAttribute("data-state", "offline");
  await expect(chip).toContainText("2 waiting");                                       // and so is the queue
  await expect(page.getByTestId("prices-as-of")).toBeVisible();                        // plain words about the age of prices

  // hold it offline (kept on this device), and see that closing needs a connection
  await page.getByRole("button", { name: "Hold", exact: true }).click();
  await expect(page.getByText("Sale held")).toBeVisible();
  await page.getByRole("button", { name: "Close till" }).click();
  await expect(page.getByText("Closing the till needs a connection.")).toBeVisible();

  // the queue screen lists both sales, waiting
  await chip.click();
  const queue = page.getByRole("dialog");
  await expect(queue.getByTestId("queue-list").getByRole("listitem")).toHaveCount(2);
  await expect(queue.getByText("To be confirmed").first()).toBeVisible();
  await queue.getByRole("button", { name: "Close", exact: true }).first().click();

  // sale C is made now; its answer will be lost on the way
  await search.fill(glue.sku);
  await search.press("Enter");
  await page.getByRole("button", { name: "One more" }).click();
  await page.getByRole("button", { name: "One more" }).click();
  await page.getByRole("button", { name: /^Pay/ }).click();
  await page.getByRole("button", { name: "Save sale" }).click();                     // 3 glue = 12.00
  await expect(page.getByTestId("sale-number")).toHaveText(/-0003$/);
  await page.getByRole("button", { name: "New sale" }).click();
  await expect(chip).toContainText("3 waiting");

  // --- the connection returns; the server gets each sale, but the first answer is dropped on the way back
  let dropped = 0;
  await page.route("**/api/v1/pos/sync/upload", async (route) => {
    if (dropped === 0) {
      dropped++;
      await route.fetch();          // the server receives and records the sale ...
      await route.abort("failed");  // ... but the terminal never hears back
    } else {
      await route.continue();
    }
  });
  await context.setOffline(false);
  await expect(chip).toHaveAttribute("data-state", "online", { timeout: 60_000 });
  expect(dropped).toBe(1);

  // every sale is at the server exactly once, at the right total, marked as made offline
  const sales = await api.get<any[]>(`/pos/sales?till_session_id=${till.id}&limit=50`);
  expect(sales.map((x) => Number(x.total)).sort((a, b) => a - b)).toEqual([4, 12, 20]);
  for (const sale of sales) {
    expect(sale.synced_offline).toBe(true);
    expect(sale.number).not.toMatch(/^OFFLINE/);
  }
  const first = sales.find((x) => Number(x.total) === 20);
  expect(Math.abs(Date.parse(first.sold_at) - madeA)).toBeLessThan(60_000);            // the moment of the sale, not of the upload
  const stock = await api.get<{ product_id: string; quantity: string }[]>("/inventory/balances");
  const qty = (id: string) => Number(stock.find((b) => b.product_id === id)?.quantity);
  expect(qty(rope.id)).toBe(48);
  expect(qty(glue.id)).toBe(26);                                                       // 30 - 1 - 3

  // the sale held offline was uploaded when the connection came back
  await expect.poll(async () => (await api.get<any[]>(`/pos/tills/${till.id}/held`)).length, { timeout: 30_000 }).toBe(1);
  await page.getByRole("button", { name: /^Held/ }).click();
  await page.getByRole("button", { name: "Resume" }).click();
  await expect.poll(async () => (await api.get<any[]>(`/pos/tills/${till.id}/held`)).length).toBe(0);
  await expect(page.getByText(rope.name).first()).toBeVisible();

  // online: hold and resume go through the server, and neither moves stock
  await page.getByRole("button", { name: "Hold", exact: true }).click();
  await expect.poll(async () => (await api.get<any[]>(`/pos/tills/${till.id}/held`)).length).toBe(1);
  expect(qty(rope.id)).toBe(48);
  await page.getByRole("button", { name: /^Held/ }).click();
  await page.getByRole("button", { name: "Resume" }).click();
  await page.getByRole("button", { name: /^Pay/ }).click();
  await page.getByRole("button", { name: "Complete sale" }).click();
  await expect(page.getByText("Sale complete")).toBeVisible();
  await page.getByRole("button", { name: "New sale" }).click();
  expect((await api.get<any[]>(`/pos/sales?till_session_id=${till.id}&limit=50`)).length).toBe(4);

  // nothing is left to send; the till closes with its true totals: 100 float + 20 + 4 + 12 + 10 = 146 in the drawer
  await page.getByRole("button", { name: "Close till" }).click();
  await expect(page.getByText("146.00").first()).toBeVisible();

  // going offline and online again is not an error on any request the journey checks (the failures are the point)
  problems.splice(0, problems.length, ...problems.filter((p) => !/INTERNET_DISCONNECTED|ERR_FAILED|Cannot reach|net::/.test(p)));
});

/** How many parts the copy of prices kept on this device has (0 until it has been fetched). */
async function savedCopy(page: import("@playwright/test").Page): Promise<number> {
  return page.evaluate(() => new Promise<number>((resolve) => {
    const open = indexedDB.open("ziira-pos");
    open.onerror = () => resolve(0);
    open.onsuccess = () => {
      const db = open.result;
      if (!db.objectStoreNames.contains("kv")) { resolve(0); return; }
      const req = db.transaction("kv").objectStore("kv").getAll();
      req.onsuccess = () => {
        const cache = (req.result as any[]).find((v) => v && Array.isArray(v.items) && v.fetchedAt);
        resolve(cache ? cache.items.length : 0);
        db.close();
      };
      req.onerror = () => resolve(0);
    };
  }));
}

// If this browser cannot store anything (private window, storage blocked), selling without a connection is refused plainly:
// the terminal never pretends to have kept a sale it could not keep.
test("J11b a browser that cannot store refuses to sell offline", async ({ page, context, problems }) => {
  const s = shared();
  const api = await signedInApi(s.owner);
  await closeOpenTills(api);
  const cat = await seedCatalogue(api, [{ name: "Wire", price: 3, cost: 1, qty: 10 }]);
  await page.addInitScript(() => { Object.defineProperty(window, "indexedDB", { value: undefined, configurable: true }); });

  await signIn(page, s.owner);
  await page.goto("/pos/terminal");
  await page.getByLabel(lbl("Till (device)")).selectOption(cat.deviceId);
  await page.getByLabel(lbl("Opening float")).fill("10");
  await page.getByRole("button", { name: "Open till and start selling" }).click();
  const search = page.getByLabel("Search or scan: name, SKU or barcode");
  await expect(search).toBeVisible();
  await expect(page.getByTestId("sync-banner")).toContainText("cannot keep sales on this device");

  await search.fill(cat.products[0].sku);
  await search.press("Enter");
  await context.setOffline(true);
  await expect(page.getByTestId("sync-chip")).toHaveAttribute("data-state", "offline");
  await page.getByRole("button", { name: /^Pay/ }).click();
  await expect(page.getByText(/this browser cannot keep the sale on this device/i)).toBeVisible();
  await expect(page.getByRole("button", { name: "Save sale" })).toBeDisabled();
  await context.setOffline(false);
  await expect(page.getByTestId("sync-chip")).toHaveAttribute("data-state", "online", { timeout: 60_000 });
  await expect(page.getByRole("button", { name: "Complete sale" })).toBeEnabled();     // online it sells as usual
  await page.getByRole("button", { name: "Complete sale" }).click();
  await expect(page.getByText("Sale complete")).toBeVisible();
  problems.splice(0, problems.length, ...problems.filter((p) => !/INTERNET_DISCONNECTED|ERR_FAILED|Cannot reach|net::/.test(p)));
});
