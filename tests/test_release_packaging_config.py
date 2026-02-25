import unittest
from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover
    import tomli as tomllib

ROOT = Path(__file__).resolve().parents[1]


class ReleasePackagingConfigTests(unittest.TestCase):

    def test_pyproject_manages_runtime_and_optional_dependencies(self) -> None:
        pyproject_path = ROOT / "pyproject.toml"
        self.assertTrue(pyproject_path.exists(), "缺少 pyproject.toml")

        data = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))
        self.assertIn("build-system", data)
        self.assertIn("project", data)

        project = data["project"]
        self.assertEqual(project["requires-python"], ">=3.10")

        dependencies = set(project["dependencies"])
        expected_runtime_dependencies = {
            "anyio==4.12.1",
            "beautifulsoup4==4.14.3",
            "bs4==0.0.2",
            "certifi==2026.1.4",
            "h11==0.16.0",
            "httpcore==1.0.9",
            "httpx==0.28.1",
            "idna==3.11",
            "lxml==6.0.2",
            "playwright==1.49.0",
            "pyqt5==5.15.11",
            "pyqt5-sip==12.18.0",
            "soupsieve==2.8.1",
            "typing-extensions==4.15.0",
            "pyqt5-qt5==5.15.2; platform_system==\"Windows\"",
        }
        self.assertTrue(
            expected_runtime_dependencies.issubset(dependencies),
            "pyproject.toml 运行依赖不完整",
        )

        optional_dependencies = project["optional-dependencies"]
        self.assertIn("dev", optional_dependencies)
        self.assertIn("build", optional_dependencies)
        self.assertIn("pylint==4.0.4", optional_dependencies["dev"])
        self.assertIn("yapf==0.43.0", optional_dependencies["dev"])
        self.assertIn(
            'tomli==2.2.1; python_version<"3.11"',
            optional_dependencies["dev"],
        )
        self.assertIn("PyInstaller==6.16.0", optional_dependencies["build"])
        self.assertIn("Pillow==11.3.0", optional_dependencies["build"])

    def test_lint_workflow_uses_pyproject_and_validates_key_tests(self) -> None:
        text = (ROOT / ".github" / "workflows" /
                "lint.yml").read_text(encoding="utf-8")
        self.assertNotIn("requirements", text)
        self.assertIn('python-version: ["3.10", "3.11"]', text)
        self.assertIn('python -m pip install ".[dev]"', text)
        self.assertIn(
            "python -m yapf --diff --recursive app tests gui.py", text
        )
        self.assertIn("python -m pylint $(find . -name \"*.py\"", text)
        self.assertIn("python -m unittest tests.test_package_layout", text)
        self.assertIn("tests.test_release_packaging_config", text)

    def test_release_workflow_uses_dual_stage_and_fixed_targets(self) -> None:
        text = (ROOT / ".github" / "workflows" /
                "release.yml").read_text(encoding="utf-8")
        self.assertIn("windows-2022", text)
        self.assertIn("macos-14", text)
        self.assertIn("target: windows-x64", text)
        self.assertIn("target: macos-arm64", text)
        self.assertIn("\n  release:\n", text)
        self.assertNotIn("requirements_file", text)
        self.assertNotIn("pip install -r", text)
        self.assertIn('python -m pip install ".[build]"', text)
        self.assertIn("actions/upload-artifact@v4", text)
        self.assertIn("actions/download-artifact@v4", text)
        self.assertNotIn("RUNNER_TEMP", text)
        self.assertNotIn("GITHUB_ENV", text)
        self.assertIn('APP_ICON_SCALE: "0.85"', text)
        self.assertIn('DMG_ICON_SIZE: "104"', text)
        self.assertNotIn("python -m playwright install chromium", text)
        self.assertNotIn("--collect-all playwright", text)
        self.assertIn("APP_ICON_SCALE", text)
        self.assertIn("--icon-size ${{ env.DMG_ICON_SIZE }}", text)
        self.assertNotIn("Contents/Resources/ms-playwright", text)
        self.assertNotIn("dist\\\\ms-playwright", text)
        self.assertNotIn("${{ runner.temp }}", text)
        self.assertIn("-windows-x64.zip", text)
        self.assertIn("-macos-arm64.dmg", text)


if __name__ == "__main__":
    unittest.main()
