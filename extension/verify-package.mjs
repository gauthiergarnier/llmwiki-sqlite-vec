import { execFileSync } from "node:child_process";
import { existsSync, readFileSync, readdirSync } from "node:fs";
import { join, relative } from "node:path";
import { fileURLToPath } from "node:url";

const root = fileURLToPath(new URL(".", import.meta.url));
const output = join(root, ".output", "chrome-mv3");
const packageJson = JSON.parse(readFileSync(join(root, "package.json"), "utf8"));
const manifest = JSON.parse(readFileSync(join(output, "manifest.json"), "utf8"));
const zipPath = join(
  root,
  ".output",
  `${packageJson.name}-${packageJson.version}-chrome.zip`,
);

function assert(condition, message) {
  if (!condition) throw new Error(message);
}

function parseEnvFile(path) {
  if (!existsSync(path)) return {};
  const values = {};
  for (const line of readFileSync(path, "utf8").split(/\r?\n/u)) {
    const match = line.match(/^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*?)\s*$/u);
    if (!match || match[1].startsWith("#")) continue;
    let value = match[2];
    if (
      value.length >= 2
      && ((value.startsWith('"') && value.endsWith('"'))
        || (value.startsWith("'") && value.endsWith("'")))
    ) {
      value = value.slice(1, -1);
    }
    values[match[1]] = value;
  }
  return values;
}

const dotenv = {};
for (const filename of [
  ".env.production.chrome.local",
  ".env.production.chrome",
  ".env.chrome.local",
  ".env.chrome",
  ".env.production.local",
  ".env.production",
  ".env.local",
  ".env",
]) {
  for (const [name, value] of Object.entries(parseEnvFile(join(root, filename)))) {
    if (!(name in dotenv)) dotenv[name] = value;
  }
}

function configured(name, fallback = "") {
  return process.env[name]?.trim() || dotenv[name]?.trim() || fallback;
}

function expectedOrigin(name, value) {
  try {
    const url = new URL(value);
    assert(
      url.protocol === "http:" || url.protocol === "https:",
      `${name} must be an HTTP(S) URL`,
    );
    return url.origin;
  } catch (error) {
    if (error instanceof Error && error.message.includes(name)) throw error;
    throw new Error(`${name} must be an absolute HTTP(S) URL`);
  }
}

const apiUrl = configured("VITE_API_BASE_URL", "https://api.llmwiki.app");
const supabaseUrl = configured("VITE_SUPABASE_URL");
const supabaseAnonKey = configured("VITE_SUPABASE_ANON_KEY");
assert(supabaseUrl, "VITE_SUPABASE_URL is required for package verification");
assert(supabaseAnonKey, "VITE_SUPABASE_ANON_KEY is required for package verification");
const apiOrigin = expectedOrigin("VITE_API_BASE_URL", apiUrl);
const supabaseOrigin = expectedOrigin("VITE_SUPABASE_URL", supabaseUrl);

if (process.env.PACKAGE_VALIDATION_MODE !== "test") {
  assert(
    !/(?:placeholder|xxxxx|example\.com)/iu.test(apiUrl),
    "release package uses a placeholder API URL",
  );
  assert(
    !/(?:placeholder|xxxxx|example\.com)/iu.test(supabaseUrl),
    "release package uses a placeholder Supabase URL",
  );
  assert(
    supabaseAnonKey.length >= 20 && !/(?:placeholder|xxxxx|eyJ\.\.\.)/iu.test(supabaseAnonKey),
    "release package uses a placeholder Supabase anon key",
  );
}

assert(
  manifest.version === packageJson.version,
  `manifest version ${manifest.version} does not match package version ${packageJson.version}`,
);
assert(manifest.manifest_version === 3, "release must use Manifest V3");
assert(manifest.action?.default_popup === "popup.html", "popup entrypoint is missing");
assert(manifest.background?.service_worker, "background service worker is missing");
assert(manifest.permissions?.includes("offscreen"), "offscreen permission is missing");
assert(
  manifest.host_permissions?.includes(`${apiOrigin}/*`),
  `API host permission is missing for ${apiOrigin}`,
);
assert(
  manifest.host_permissions?.includes(`${supabaseOrigin}/*`),
  `Supabase Auth host permission is missing for ${supabaseOrigin}`,
);

const requiredFiles = [
  "background.js",
  "content-scripts/content.js",
  "manifest.json",
  "offscreen.html",
  "popup.html",
];
for (const file of requiredFiles) {
  assert(existsSync(join(output, file)), `build output is missing ${file}`);
}
assert(existsSync(zipPath), `release archive is missing: ${zipPath}`);

const zipEntries = new Set(
  execFileSync("unzip", ["-Z1", zipPath], { encoding: "utf8" })
    .split(/\r?\n/u)
    .filter((entry) => entry && !entry.endsWith("/")),
);
for (const file of requiredFiles) {
  assert(zipEntries.has(file), `release archive is missing ${file}`);
}

function outputFiles(directory) {
  const files = [];
  for (const entry of readdirSync(directory, { withFileTypes: true })) {
    const path = join(directory, entry.name);
    if (entry.isDirectory()) files.push(...outputFiles(path));
    else if (entry.isFile()) files.push(relative(output, path).replaceAll("\\", "/"));
  }
  return files.sort();
}

const builtFiles = outputFiles(output);
assert(
  builtFiles.length === zipEntries.size
    && builtFiles.every((file) => zipEntries.has(file)),
  "archive entries do not exactly match the current build output",
);

let archivedManifest;
for (const file of builtFiles) {
  const built = readFileSync(join(output, file));
  const archived = execFileSync("unzip", ["-p", zipPath, file], {
    maxBuffer: 20 * 1024 * 1024,
  });
  assert(built.equals(archived), `archived ${file} is stale or corrupted`);
  if (file === "manifest.json") archivedManifest = JSON.parse(archived.toString("utf8"));
}

assert(
  archivedManifest.version === packageJson.version,
  `archived manifest version ${archivedManifest.version} is stale`,
);

const background = readFileSync(join(output, manifest.background.service_worker), "utf8");
assert(background.includes(supabaseUrl), "background bundle has the wrong Supabase URL");
assert(background.includes(supabaseAnonKey), "background bundle has the wrong Supabase anon key");

console.log(`Verified ${zipPath}`);
