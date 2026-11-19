"use strict";
// Test driver only. No code or credentials are sent to the public site.
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const { chromium } = require(path.join(__dirname, "../../../node_modules/playwright"));
const fixture = JSON.parse(fs.readFileSync(0, "utf8"));
const origin = new URL(fixture.base).origin;
assert.equal(new URL(origin).hostname, "127.0.0.1");

(async () => {
  const browser = await chromium.launch({channel:"msedge", args:["--disable-background-networking","--no-proxy-server"]});
  const results = [];
  try {
    for (const [device,width,height] of [["desktop",1440,900],["mobile",390,844]]) {
      const context = await browser.newContext({viewport:{width,height},isMobile:device==="mobile",hasTouch:device==="mobile",
        deviceScaleFactor:1,locale:"zh-CN",reducedMotion:"reduce",serviceWorkers:"block"});
      await context.addCookies([{...fixture.cookie,url:origin,httpOnly:true,sameSite:"Lax"}]);
      await context.route("**/*",route=>new URL(route.request().url()).origin===origin?route.continue():route.abort());
      const tab = await context.newPage();
      for (const key of ["event","match","bp","admin_match"]) {
        const missing = new Set(), failures = [], consoleErrors = [];
        const record = reply => { if(reply.status()>=400) missing.add(new URL(reply.url()).pathname); };
        const failed = req => { if(new URL(req.url()).origin===origin) missing.add(new URL(req.url()).pathname); };
        const unexpected = error => failures.push(error.message);
        const consoleError = msg => { if(msg.type()==="error") consoleErrors.push(msg.text()); };
        tab.on("response",record); tab.on("requestfailed",failed); tab.on("pageerror",unexpected); tab.on("console",consoleError);
        assert.equal((await tab.goto(origin+fixture[key],{waitUntil:"load"})).status(),200);
        await tab.evaluate(() => document.fonts.ready);
        if (key !== "admin_match") assert.ok((await tab.locator("body").innerText()).includes(fixture.team), key);
        if (key === "event") assert.equal(await tab.locator(".event-reg-team").count(),2);
        await tab.keyboard.press("Tab");
        const scroll = await tab.evaluate(() => Math.max(document.documentElement.scrollWidth, document.body.scrollWidth));
        await tab.screenshot({path:path.join(fixture.output,key+"-"+device+".png"),animations:"disabled"});
        tab.off("response",record); tab.off("requestfailed",failed); tab.off("pageerror",unexpected); tab.off("console",consoleError);
        const result={device,page:key,width,scroll,failed_requests:[...missing],page_errors:failures,console_errors:consoleErrors};
        results.push(result);
        assert.ok(scroll<=width && !missing.size && !failures.length && !consoleErrors.length,JSON.stringify(result));
      }
      await context.clearCookies();
      await context.addCookies([{...fixture.players[device],url:origin,httpOnly:true,sameSite:"Lax"}]);
      assert.equal((await tab.goto(origin+fixture.signup,{waitUntil:"load"})).status(),200);
      const signup=tab.locator('[data-registration-kind="individual"]');
      const [receipt]=await Promise.all([
        tab.waitForResponse(r=>r.request().method()==="POST" && r.url().endsWith("/register-individual")),
        signup.getByRole("button",{name:"选择个人报名"}).click()
      ]);
      assert.equal(receipt.status(),200);
      assert.equal((await receipt.json()).success,true);
      await signup.getByRole("button",{name:"取消个人报名"}).waitFor();
      await tab.screenshot({path:path.join(fixture.output,"signup-"+device+".png"),animations:"disabled"});
      await context.close();
    }
    fs.writeFileSync(path.join(fixture.output,"review.json"),JSON.stringify(results,null,2));
    process.stdout.write(JSON.stringify(results)+"\n");
  } finally {
    await browser.close();
  }
})().catch(error=>{console.error(error); process.exitCode=1;});
