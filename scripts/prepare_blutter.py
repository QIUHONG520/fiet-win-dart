#!/usr/bin/env python3
"""Prepare a worawit/blutter checkout for building the fiet-win-dart engine.

Derived from QIUHONG520/fler-dart scripts/build-dartvm.sh (pinned blutter commit
4a60ac648bf448c5a7596437243bcd0b9376fdf0). Only the source patches that are
required for the wrapper/DLL build are applied here; Android/NDK-specific steps
(NDK toolchain injection, static ICU/capstone cross builds, regexp exclusion)
are intentionally NOT applied — Windows uses blutter's native MSVC/Dart-VM path.

Steps (all idempotent):
  1. DartApp.h: fler_libs()/fler_native_lib() accessors (direct in-memory export)
  2. DartDumper.h: FlPoolDescription() wrapper
  3. FridaWriter.cpp: tolerant frida.template.js copy (missing template must not crash)
  4. CodeAnalyzer*: write-barrier false-positive ASSERT -> InsnException guard
  5. patches/patch-blutter-robust.py: bounds checks / per-function recovery /
     Dart 2.14-3.12 compatibility patches
  6. DartLoader.cpp: Dart_ExitIsolate before Dart_ShutdownIsolate (VM reuse)
  7. scripts/CMakeLists.txt (Dart VM template): /Zc:preprocessor + /utf-8 for MSVC

Usage: python scripts/prepare_blutter.py <blutter_dir> [--expected-commit SHA]
"""
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ROBUST_PATCH = os.path.join(HERE, "patches", "patch-blutter-robust.py")
EXPECTED_COMMIT = "4a60ac648bf448c5a7596437243bcd0b9376fdf0"


def log(msg):
    print(f"[prepare_blutter] {msg}", flush=True)


def read(path):
    with open(path, encoding="utf-8") as f:
        return f.read()


def write(path, text):
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)


def patch_dartapp_h(blutter_dir):
    path = os.path.join(blutter_dir, "blutter", "src", "DartApp.h")
    s = read(path)
    if "fler_libs" not in s:
        accessor = (
            "\n\t// fler-dart: accessors for direct in-memory DB export\n"
            "\tconst std::vector<DartLibrary*>& fler_libs() const { return libs; }\n"
            "\tDartLibrary* fler_native_lib() { return &nativeLib; }\n\n"
        )
        needle = "\nprivate:\n"
        assert needle in s, "DartApp.h private: marker not found"
        s = s.replace(needle, accessor + needle, 1)
        write(path, s)
        log("DartApp.h: accessors added")
    elif "fler_native_lib" not in s:
        needle = "\tconst std::vector<DartLibrary*>& fler_libs() const { return libs; }"
        assert needle in s
        s = s.replace(needle, needle + "\n\tDartLibrary* fler_native_lib() { return &nativeLib; }", 1)
        write(path, s)
        log("DartApp.h: fler_native_lib() added")
    else:
        log("DartApp.h: already patched")


def patch_dartdumper_h(blutter_dir):
    path = os.path.join(blutter_dir, "blutter", "src", "DartDumper.h")
    s = read(path)
    if "FlPoolDescription" in s:
        log("DartDumper.h: already patched")
        return
    wrapper = (
        "\n\t// fler-dart: expose pool description for direct in-memory DB export\n"
        "\tstd::string FlPoolDescription(intptr_t offset, bool simpleForm = true) {\n"
        "\t\treturn getPoolObjectDescription(offset, simpleForm);\n"
        "\t}\n\n"
    )
    needle = "\nprivate:\n"
    assert needle in s, "DartDumper.h private: marker not found"
    s = s.replace(needle, wrapper + needle, 1)
    write(path, s)
    log("DartDumper.h: FlPoolDescription() added")


def patch_fridawriter(blutter_dir):
    path = os.path.join(blutter_dir, "blutter", "src", "FridaWriter.cpp")
    s = read(path)
    if "fler-dart tolerant template" in s:
        log("FridaWriter.cpp: already patched")
        return
    old = (
        'std::filesystem::copy_file(FRIDA_TEMPLATE_DIR "/frida.template.js", filename, '
        "std::filesystem::copy_options::overwrite_existing);"
    )
    new = (
        "// fler-dart tolerant template copy: missing template no longer crashes\n"
        "std::error_code _ec;\n"
        'std::filesystem::copy_file(FRIDA_TEMPLATE_DIR "/frida.template.js", filename,\n'
        "    std::filesystem::copy_options::overwrite_existing, _ec);"
    )
    assert old in s, "FridaWriter.cpp copy_file pattern not found"
    write(path, s.replace(old, new))
    log("FridaWriter.cpp: tolerant template copy applied")


def patch_write_barrier(blutter_dir):
    root = os.path.join(blutter_dir, "blutter", "src")
    count = 0
    for name in ("CodeAnalyzer.cpp", "CodeAnalyzer_arm64.cpp"):
        path = os.path.join(root, name)
        if not os.path.isfile(path):
            continue
        lines = read(path).splitlines(True)
        out = []
        changed = False
        for line in lines:
            if "CSREG_DART_HEAP" in line and re.search(
                r"\b(?:ASSERT|RELEASE_ASSERT|FATAL)\s*\(", line
            ):
                indent = line[: len(line) - len(line.lstrip())]
                out.append(
                    indent
                    + 'throw InsnException("write barrier register mismatch", insn); // fler-dart wb-guard\n'
                )
                count += 1
                changed = True
            else:
                out.append(line)
        if changed:
            write(path, "".join(out))
    log(f"write-barrier assertion guards added: {count}")


def patch_robust(blutter_dir):
    root = os.path.join(blutter_dir, "blutter", "src")
    script = ROBUST_PATCH
    if not os.path.isfile(script):
        raise SystemExit(f"missing {script}")
    log("applying patch-blutter-robust.py ...")
    subprocess.run([sys.executable, script, root], check=True)


def patch_dartloader(blutter_dir):
    path = os.path.join(blutter_dir, "blutter", "src", "DartLoader.cpp")
    if not os.path.isfile(path):
        log("DartLoader.cpp not found, skip")
        return
    s = read(path)
    if "fler-dart isolate-detach" in s:
        log("DartLoader.cpp: already patched")
        return
    old = "\t\tDart_ShutdownIsolate();"
    if old not in s:
        log("WARN: DartLoader.dart shutdown target not found")
        return
    new = (
        "\t\t// fler-dart isolate-detach: detach before shutdown so the thread\n"
        "\t\t// can create the next isolate when the App reuses this IO thread.\n"
        "\t\tDart_ExitIsolate();\n"
        "\t\tDart_ShutdownIsolate();"
    )
    write(path, s.replace(old, new, 1))
    log("DartLoader.cpp: isolate detach added")


def patch_dartvm_cmake_template(blutter_dir):
    path = os.path.join(blutter_dir, "scripts", "CMakeLists.txt")
    s = read(path)
    changed = False
    if "/Zc:preprocessor" not in s:
        s = s.replace("/Oy /GR- /EHs-c-", "/Oy /GR- /EHs-c- /Zc:preprocessor", 1)
        changed = True
    if "/utf-8" not in s:
        s = s.replace("/Zc:preprocessor", "/Zc:preprocessor /utf-8", 1)
        changed = True
    if changed:
        write(path, s)
        log("Dart VM CMake template: MSVC /Zc:preprocessor /utf-8 added")
    else:
        log("Dart VM CMake template: already patched")


def check_commit(blutter_dir):
    try:
        out = subprocess.run(
            ["git", "-C", blutter_dir, "rev-parse", "HEAD"],
            capture_output=True, text=True, check=True,
        ).stdout.strip()
    except Exception as e:  # noqa: BLE001
        log(f"WARN: cannot read blutter HEAD ({e})")
        return
    log(f"blutter HEAD = {out}")
    if out != EXPECTED_COMMIT:
        log(f"WARN: expected {EXPECTED_COMMIT}; patches target that tree")


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    blutter_dir = os.path.abspath(sys.argv[1])
    if not os.path.isdir(os.path.join(blutter_dir, "blutter", "src")):
        raise SystemExit(f"not a blutter checkout: {blutter_dir}")
    check_commit(blutter_dir)
    patch_dartapp_h(blutter_dir)
    patch_dartdumper_h(blutter_dir)
    patch_fridawriter(blutter_dir)
    patch_write_barrier(blutter_dir)
    patch_robust(blutter_dir)
    patch_dartloader(blutter_dir)
    patch_dartvm_cmake_template(blutter_dir)
    log("done")
    return 0


if __name__ == "__main__":
    sys.exit(main())
