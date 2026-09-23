import { readFileSync } from "node:fs";
import { expect, test } from "vitest";
import environments from "../../../deployment/cloud/environments.json";
import { fillLinks, linksFor } from "./links";

const page = (name: string) => readFileSync(new URL(`../${name}`, import.meta.url), "utf8");

test("each deployed build links to its own environment's app", () => {
  expect(linksFor("staging", environments)).toEqual({
    app: "https://app.staging.tadas.fyi",
    site: "https://www.staging.tadas.fyi",
    github: "https://github.com/baristaze/tadas",
  });
  expect(linksFor("production", environments).app).toBe("https://app.tadas.fyi");
  expect(linksFor("production", environments).site).toBe("https://www.tadas.fyi");
});

test("a build for no known environment is refused", () => {
  expect(() => linksFor("prod", environments)).toThrow(/staging or production/);
});

test("a placeholder no link fills fails the build", () => {
  const links = linksFor("staging", environments);
  expect(fillLinks('<a href="%APP_URL%/login">', links)).toBe('<a href="https://app.staging.tadas.fyi/login">');
  expect(() => fillLinks('<a href="%DOCS_URL%">', links)).toThrow(/%DOCS_URL%/);
});

// The page loads nothing from another origin: no script, no font, no image,
// no stylesheet. Only a link a person follows may leave the site.
test.each(["index.html", "404.html"])("%s loads nothing from another origin and runs no script", (name) => {
  const html = page(name);
  expect(html).not.toMatch(/<script\b/i);
  expect(html).not.toMatch(/<iframe\b/i);
  for (const match of html.matchAll(/<(?:link|img|source|video|audio)\b[^>]*\b(?:href|src|srcset)="([^"]+)"/gi)) {
    const url = match[1] ?? "";
    const followed = /rel="canonical"/.test(match[0]);
    if (!followed) expect(url, `${name}: ${match[0]}`).not.toMatch(/^(https?:)?\/\//);
  }
});

test("the sign-in and sign-up links go to the app of the build's environment", () => {
  const html = page("index.html");
  expect(html).toContain('href="%APP_URL%/login"');
  expect(html).toContain('href="%APP_URL%/login?screen_hint=sign-up"');
  expect(html).toContain('href="%GITHUB_URL%"');
  expect(html).not.toMatch(/tadas\.fyi/);
});

test("the plans carry their prices", () => {
  const text = page("index.html").replace(/<[^>]+>/g, " ").replace(/\s+/g, " ");
  expect(text).toMatch(/Free \$0/);
  expect(text).toMatch(/Up to 10 open tasks/);
  expect(text).toMatch(/No API key/);
  expect(text).toMatch(/Pro \$5 \/ month/);
  expect(text).toMatch(/Team \$10 \/ month/);
  expect(text).toMatch(/Up to 5 members/);
  expect(text).toMatch(/Max \$3 \/ member \/ month/);
  expect(text).toMatch(/\$30 a month minimum/);
  expect(text).not.toMatch(/illustrative/i);
});
