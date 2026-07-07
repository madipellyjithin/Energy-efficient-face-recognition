from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import urllib.request
import zipfile
from pathlib import Path


MIN_PYTHON = (3, 10)
DEFAULT_VENV_DIRNAME = ".venv"
DEFAULT_RUNTIME_DIRNAME = "runtime"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Hands-free backend bootstrapper for the Split Face System client."
    )
    parser.add_argument(
        "--source-url",
        help="Optional zip URL for downloading the project before setup.",
    )
    parser.add_argument(
        "--zip-file",
        help="Optional local zip file to extract before setup.",
    )
    parser.add_argument(
        "--install-dir",
        default="client_install",
        help="Install directory used with --source-url or --zip-file. Default: %(default)s",
    )
    parser.add_argument(
        "--project-dir",
        help="Use an existing extracted project directory. Defaults to this script's directory.",
    )
    parser.add_argument(
        "--venv-dir",
        default=DEFAULT_VENV_DIRNAME,
        help="Virtual environment folder name or path. Default: %(default)s",
    )
    parser.add_argument(
        "--python",
        default=sys.executable,
        help="Python executable to use for creating the virtual environment.",
    )
    parser.add_argument(
        "--host",
        default="0.0.0.0",
        help="Host used when creating the launcher script. Default: %(default)s",
    )
    parser.add_argument(
        "--port",
        default="5000",
        help="Port used when creating the launcher script. Default: %(default)s",
    )
    parser.add_argument(
        "--start",
        action="store_true",
        help="Start the backend after setup finishes.",
    )
    parser.add_argument(
        "--detached",
        action="store_true",
        help="When used with --start on Windows, run the backend in the background and write logs to runtime/.",
    )
    return parser.parse_args()


def ensure_python_version() -> None:
    if sys.version_info < MIN_PYTHON:
        dotted = ".".join(str(part) for part in MIN_PYTHON)
        raise SystemExit(f"Python {dotted}+ is required. Current version: {sys.version.split()[0]}")


def ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path


def download_file(url: str, target: Path) -> Path:
    print(f"Downloading project zip from {url}")
    ensure_dir(target.parent)
    with urllib.request.urlopen(url) as response, target.open("wb") as handle:
        shutil.copyfileobj(response, handle)
    return target


def extract_zip(zip_path: Path, destination: Path) -> Path:
    print(f"Extracting {zip_path} into {destination}")
    if destination.exists():
        shutil.rmtree(destination)
    destination.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path, "r") as archive:
        archive.extractall(destination)

    candidates = [path for path in destination.iterdir() if path.is_dir()]
    if len(candidates) == 1 and (candidates[0] / "python_server").exists():
        return candidates[0]
    return destination


def resolve_project_dir(args: argparse.Namespace, script_dir: Path) -> Path:
    if args.project_dir:
        project_dir = Path(args.project_dir).resolve()
        if not project_dir.exists():
            raise SystemExit(f"Project directory not found: {project_dir}")
        return project_dir

    if args.source_url or args.zip_file:
        install_dir = Path(args.install_dir).resolve()
        zip_path = install_dir / "split_face_system.zip"
        if args.source_url:
            download_file(args.source_url, zip_path)
        else:
            source_zip = Path(args.zip_file).resolve()
            if not source_zip.exists():
                raise SystemExit(f"Zip file not found: {source_zip}")
            ensure_dir(install_dir)
            shutil.copy2(source_zip, zip_path)
        return extract_zip(zip_path, install_dir / "project")

    return script_dir


def run_command(command: list[str], cwd: Path | None = None) -> None:
    printable = " ".join(f'"{part}"' if " " in part else part for part in command)
    print(f"Running: {printable}")
    subprocess.run(command, cwd=cwd, check=True)


def build_venv(project_dir: Path, python_executable: str, venv_arg: str) -> tuple[Path, Path]:
    venv_path = Path(venv_arg)
    if not venv_path.is_absolute():
        venv_path = project_dir / venv_path

    if not venv_path.exists():
        run_command([python_executable, "-m", "venv", str(venv_path)], cwd=project_dir)

    if os.name == "nt":
        python_bin = venv_path / "Scripts" / "python.exe"
    else:
        python_bin = venv_path / "bin" / "python"

    if not python_bin.exists():
        raise SystemExit(f"Virtual environment python not found: {python_bin}")

    return venv_path, python_bin


def merge_env_file(example_path: Path, env_path: Path) -> None:
    if not example_path.exists():
        return

    if not env_path.exists():
        shutil.copy2(example_path, env_path)
        print(f"Created {env_path.name} from {example_path.name}")
        return

    existing_lines = env_path.read_text(encoding="utf-8").splitlines()
    existing_keys = {
        line.split("=", 1)[0].strip()
        for line in existing_lines
        if line.strip() and not line.strip().startswith("#") and "=" in line
    }
    example_lines = example_path.read_text(encoding="utf-8").splitlines()
    missing_lines = []
    for line in example_lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in line:
            continue
        key = line.split("=", 1)[0].strip()
        if key not in existing_keys:
            missing_lines.append(line)

    if missing_lines:
        with env_path.open("a", encoding="utf-8", newline="\n") as handle:
            if existing_lines and existing_lines[-1].strip():
                handle.write("\n")
            handle.write("\n".join(missing_lines) + "\n")
        print(f"Added {len(missing_lines)} missing setting(s) to {env_path.name}")


def create_launcher(project_dir: Path, python_bin: Path, host: str, port: str) -> Path:
    launcher_path = project_dir / "start_backend.bat"
    content = "\n".join(
        [
            "@echo off",
            "setlocal",
            f'cd /d "{project_dir}"',
            f'set "BACKEND_HOST={host}"',
            f'set "BACKEND_PORT={port}"',
            f'"{python_bin}" "python_server\\app.py"',
            "",
        ]
    )
    launcher_path.write_text(content, encoding="utf-8", newline="\r\n")
    return launcher_path


def ensure_runtime_layout(project_dir: Path) -> Path:
    runtime_dir = ensure_dir(project_dir / DEFAULT_RUNTIME_DIRNAME)
    ensure_dir(project_dir / "python_server" / "data" / "known_faces")
    ensure_dir(project_dir / "python_server" / "models")
    return runtime_dir


def install_dependencies(project_dir: Path, python_bin: Path) -> None:
    requirements = project_dir / "python_server" / "requirements.txt"
    if not requirements.exists():
        raise SystemExit(f"Requirements file not found: {requirements}")

    run_command([str(python_bin), "-m", "pip", "install", "--upgrade", "pip", "setuptools", "wheel"])
    run_command([str(python_bin), "-m", "pip", "install", "-r", str(requirements)])


def start_backend(project_dir: Path, python_bin: Path, detached: bool) -> None:
    env = os.environ.copy()
    env.setdefault("BACKEND_HOST", "0.0.0.0")
    env.setdefault("BACKEND_PORT", "5000")

    if detached and os.name == "nt":
        runtime_dir = ensure_runtime_layout(project_dir)
        stdout_path = runtime_dir / "python_stdout.log"
        stderr_path = runtime_dir / "python_stderr.log"
        with stdout_path.open("ab") as stdout_handle, stderr_path.open("ab") as stderr_handle:
            subprocess.Popen(
                [str(python_bin), "python_server\\app.py"],
                cwd=project_dir,
                env=env,
                stdout=stdout_handle,
                stderr=stderr_handle,
                creationflags=subprocess.CREATE_NEW_CONSOLE,
            )
        print(f"Backend started in background. Logs: {stdout_path} and {stderr_path}")
        return

    print("Starting backend in the current terminal")
    subprocess.run([str(python_bin), "python_server/app.py"], cwd=project_dir, env=env, check=True)


def validate_project_layout(project_dir: Path) -> None:
    expected = [
        project_dir / "python_server" / "app.py",
        project_dir / "python_server" / "requirements.txt",
        project_dir / "python_server" / "models" / "face_detection_yunet_2023mar.onnx",
        project_dir / "python_server" / "models" / "face_recognition_sface_2021dec.onnx",
    ]
    missing = [path for path in expected if not path.exists()]
    if missing:
        joined = "\n".join(str(path) for path in missing)
        raise SystemExit(f"Project is missing required backend files:\n{joined}")


def main() -> None:
    ensure_python_version()
    args = parse_args()
    script_dir = Path(__file__).resolve().parent
    project_dir = resolve_project_dir(args, script_dir)
    validate_project_layout(project_dir)

    runtime_dir = ensure_runtime_layout(project_dir)
    print(f"Using project directory: {project_dir}")
    print(f"Runtime directory: {runtime_dir}")

    venv_path, python_bin = build_venv(project_dir, args.python, args.venv_dir)
    print(f"Virtual environment ready: {venv_path}")

    install_dependencies(project_dir, python_bin)
    merge_env_file(project_dir / "python_server" / ".env.example", project_dir / "python_server" / ".env")

    launcher_path = create_launcher(project_dir, python_bin, args.host, args.port)
    print(f"Launcher created: {launcher_path}")
    print("Setup finished successfully.")
    print(f"Run later with: {launcher_path}")

    if args.start:
        start_backend(project_dir, python_bin, args.detached)


if __name__ == "__main__":
    main()
