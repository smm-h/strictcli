const { execSync } = require("child_process");

const version = require("./package.json").version;
const pkg = `strictcli==${version}`;

try {
  execSync(`uv pip install ${pkg}`, { stdio: "inherit" });
} catch {
  try {
    execSync(`pip install ${pkg}`, { stdio: "inherit" });
  } catch {
    console.error(
      `Failed to install Python package ${pkg}. ` +
      "Ensure uv or pip is available, then run: uv add strictcli"
    );
  }
}
