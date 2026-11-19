"""Тесты Capacitor-проекта и Android CI (T-179, T-182)."""

from __future__ import annotations

import json
from pathlib import Path

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[1]
FRONTEND = PROJECT_ROOT / "frontend"


def _read(relative: str) -> str:
    return (PROJECT_ROOT / relative).read_text(encoding="utf-8")


def test_capacitor_config_declares_app_and_web_dir() -> None:
    config = _read("frontend/capacitor.config.ts")

    assert "ru.vetassistant.app" in config
    assert "webDir: 'dist'" in config
    assert "androidScheme: 'https'" in config
    assert "SplashScreen" in config
    assert "StatusBar" in config
    assert "Keyboard" in config


def test_android_project_exists() -> None:
    android = FRONTEND / "android"
    assert (android / "app" / "src" / "main" / "AndroidManifest.xml").exists()
    assert (android / "gradlew").exists()
    assert (android / "variables.gradle").exists()

    manifest = (
        android / "app" / "src" / "main" / "AndroidManifest.xml"
    ).read_text(encoding="utf-8")
    assert "ru.vetassistant.app" in (
        android / "app" / "src" / "main" / "res" / "values" / "strings.xml"
    ).read_text(encoding="utf-8")
    assert "android.permission.INTERNET" in manifest
    assert "MainActivity" in manifest
    assert 'android:scheme="vetassistant"' in manifest
    assert "android.intent.action.VIEW" in manifest


def test_android_icons_and_splash_are_custom() -> None:
    res = FRONTEND / "android" / "app" / "src" / "main" / "res"
    assert (res / "mipmap-xxxhdpi" / "ic_launcher.png").exists()
    assert (res / "drawable-port-xhdpi" / "splash.png").exists()
    assert (res / "drawable-land-xhdpi" / "splash.png").exists()


def test_gradle_build_supports_signed_release() -> None:
    gradle = _read("frontend/android/app/build.gradle")

    assert "signingConfigs" in gradle
    assert "ANDROID_KEYSTORE_FILE" in gradle
    assert "ANDROID_KEYSTORE_PASSWORD" in gradle
    assert "ANDROID_KEY_ALIAS" in gradle
    assert "ANDROID_VERSION_CODE" in gradle
    assert "signingConfig signingConfigs.release" in gradle


def test_frontend_scripts_include_android_workflow() -> None:
    package = json.loads(_read("frontend/package.json"))
    scripts = package["scripts"]

    assert "android:add" in scripts
    assert "android:sync" in scripts
    assert "android:build" in scripts
    assert "android:open" in scripts


def test_ci_has_android_build_job() -> None:
    workflow = yaml.safe_load(_read(".github/workflows/ci.yml"))
    jobs = workflow["jobs"]

    assert "android-build" in jobs
    steps = jobs["android-build"]["steps"]
    commands = " ".join(str(step.get("run", "")) for step in steps)
    assert "cap sync android" in commands
    assert "assembleDebug" in commands
    assert "bundleRelease" in commands


def test_release_workflow_can_attach_android_assets() -> None:
    workflow = yaml.safe_load(_read(".github/workflows/release.yml"))
    jobs = workflow["jobs"]

    assert "android-release" in jobs
    steps = jobs["android-release"]["steps"]
    assert any(
        "action-gh-release" in str(step.get("uses", "")) for step in steps
    )
