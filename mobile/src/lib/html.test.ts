import assert from "node:assert/strict";
import { test } from "node:test";
import { esc } from "./html.ts";

test("escapes every character that can open markup", () => {
  assert.equal(esc(`<b>&"'`), "&lt;b&gt;&amp;&quot;&#39;");
});

test("escapes the ampersand first, so entities are not double-built", () => {
  // Naive ordering turns "<" into "&lt;" and then the "&" pass rewrites it
  // into "&amp;lt;", which renders the literal text "&lt;" on the page.
  assert.equal(esc("<"), "&lt;");
  assert.equal(esc("&lt;"), "&amp;lt;");
});

test("a transcript span cannot inject markup into a certificate", () => {
  // The respondent said this out loud; it is quoted verbatim on the PDF.
  const span = 'We are <script>alert("x")</script> accepting';
  const out = esc(span);
  assert.ok(!out.includes("<script>"));
  assert.ok(out.includes("&lt;script&gt;"));
});

test("a caller-supplied organization name cannot break out of its heading", () => {
  const org = '</h1><div style="display:none">';
  assert.ok(!esc(org).includes("</h1>"));
});

test("null and undefined render as empty, not as the word null", () => {
  assert.equal(esc(null), "");
  assert.equal(esc(undefined), "");
});

test("ordinary text passes through unchanged", () => {
  assert.equal(esc("Decatur Counseling Center"), "Decatur Counseling Center");
  assert.equal(esc(42), "42");
});
