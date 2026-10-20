#!/usr/bin/env python3
"""Prepare a Dart SDK source tree for the Windows x64 Dart VM static-lib build.

`dartvm_fetch_build.py` normally clones dart-lang/sdk itself (git sparse clone);
in restricted networks that is unreliable, so build.ps1 downloads the codeload
tarball and calls this script instead. It performs the small set of steps that
upstream `checkout_dart()` would do, plus the MSVC compatibility patches the
Dart VM build needs on Windows for Python-311 / VS2022 / recent Dart versions.

Usage: python scripts/prepare_dartsdk.py <dart-sdk-src-dir> [--version X.Y.Z]
"""
import mmap
import os
import re
import subprocess
import sys

VA_OPT = " __VA_OPT__(,) __VA_ARGS__"


def log(msg):
    print(f"[prepare_dartsdk] {msg}", flush=True)


def patch_assert_fatal_msvc(root):
    """Dart <=3.11 assert.h has a broken `_MSC_VER` FATAL branch:

    #if defined(_MSC_VER)
    #define FATAL(format, ...)  dart::Assert(...).Fail(format, __VA_ARGS__);
    -> UNREACHABLE() => Fail("unreachable code", ) => C2059 under /Zc:preprocessor.

    Dart >=3.12 removed this branch; for older versions rewrite it with C++20
    __VA_OPT__ (the MSVC conforming preprocessor is already enabled through the
    patched Dart VM CMake template).
    """
    path = os.path.join(root, "runtime", "platform", "assert.h")
    if not os.path.isfile(path):
        return
    with open(path, encoding="utf-8") as f:
        s = f.read()
    if "fiet-win-dart: use C++20 __VA_OPT__" in s:
        log("assert.h: already patched")
        return
    pat = re.compile(
        r"#if defined\(_MSC_VER\)\n#define FATAL\(format, \.\.\.\)\s*\\\n"
        r"  dart::Assert\(__FILE__, __LINE__\)\.Fail\(format, __VA_ARGS__\);\n"
        r"#else\n#define FATAL\(format, \.\.\.\)\s*\\\n"
        r"  dart::Assert\(__FILE__, __LINE__\)\.Fail\(format, ##__VA_ARGS__\);\n"
        r"#endif\n"
    )
    new = (
        "// fiet-win-dart: use C++20 __VA_OPT__ so FATAL()/UNREACHABLE() work with\n"
        "// the MSVC conforming preprocessor (/Zc:preprocessor) on all Dart versions.\n"
        "#define FATAL(format, ...)                                                    \\\n"
        "  dart::Assert(__FILE__, __LINE__).Fail(format" + VA_OPT + ");\n"
    )
    s2, n = pat.subn(new, s, count=1)
    if n == 0:
        log("assert.h: FATAL(_MSC_VER) pattern not found (newer Dart?), skip")
        return
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(s2)
    log("assert.h: MSVC FATAL() patched with __VA_OPT__")


def patch_msvc_variadic_macros(root):
    """Dart <=3.11 headers/sources contain `#if defined(_MSC_VER)` variadic macros
    that pass an empty __VA_ARGS__ straight to a call, e.g.:

        #define THR_Print(format, ...) Log::Current()->Print(format, __VA_ARGS__)
        #define TRACE_TYPE_CHECKS_VERBOSE(format, ...) OS::PrintErr(format, __VA_ARGS__)

    THR_Print("x") then expands to Print("x", ) => C2059 with the MSVC conforming
    preprocessor. Newer Dart fixed this; for older versions rewrite every
    `, __VA_ARGS__)` occurrence under runtime/ to C++20 `__VA_OPT__(,) __VA_ARGS__`
    (idempotent: the replacement text no longer matches the literal pattern).
    """
    fixed = 0
    runtime_root = os.path.join(root, "runtime")
    for dirpath, _dirnames, filenames in os.walk(runtime_root):
        for name in filenames:
            if not name.endswith((".h", ".cc", ".cpp")):
                continue
            path = os.path.join(dirpath, name)
            try:
                with open(path, encoding="utf-8", errors="surrogateescape") as f:
                    text = f.read()
            except OSError:
                continue
            new_text = text.replace(", __VA_ARGS__)", VA_OPT + ")")
            if new_text == text:
                continue
            with open(path, "w", encoding="utf-8", errors="surrogateescape", newline="\n") as f:
                f.write(new_text)
            fixed += 1
            log(f"variadic macro patched: {os.path.relpath(path, root)}")
    if fixed == 0:
        log("variadic macros: nothing to patch")


def patch_unwinding_records_msvc(root):
    """blutter's win32 workaround: Dart >=3.8 may declare RUNTIME_FUNCTION wrongly
    when host=Windows/x64 and target=ARM64 (blutter's dartvm_fetch_build.py does
    the same byte patch). Only applied when the marked guard/static_assert exists."""
    path = os.path.join(root, "runtime", "platform", "unwinding_records.h")
    if not os.path.isfile(path):
        return
    with open(path, "r+b") as f:
        mm = mmap.mmap(f.fileno(), 0)
        try:
            marker = b"\n#if !defined(DART_HOST_OS_WINDOWS) || !defined(HOST_ARCH_ARM64)"
            pos = mm.find(marker)
            if pos != -1:
                mm[pos + 36:pos + 38] = b"//"
                log("unwinding_records.h: ARM64 guard patched")
                return
            pos = mm.find(b"\nstatic_assert(sizeof(")
            if pos != -1:
                mm[pos + 1:pos + 3] = b"//"
                log("unwinding_records.h: RUNTIME_FUNCTION static_assert commented out")
                return
        finally:
            mm.flush()
            mm.close()
    log("unwinding_records.h: no patch needed")


def check_cmakelists_patched(root):
    """The Dart VM CMake template is patched by prepare_blutter.py; verify it."""
    path = os.path.join(root, "CMakeLists.txt")
    if not os.path.isfile(path):
        return
    with open(path, encoding="utf-8") as f:
        s = f.read()
    missing = [flag for flag in ("/Zc:preprocessor", "/utf-8") if flag not in s]
    if missing:
        log(f"WARN: Dart VM CMakeLists.txt misses MSVC flags {missing}; "
            f"run prepare_blutter.py first")
    else:
        log("Dart VM CMakeLists.txt: MSVC flags present")



def patch_setjmp_address_msvc(root):
    """Dart 2.16.x thread.h takes the address of setjmp (`reinterpret_cast<void*>(&setjmp)`).

    MSVC implements setjmp as a pure intrinsic and rejects taking its address (C7552).
    The TsanUtils helper is only used by ThreadSanitizer builds, so a nullptr is enough
    for our non-TSAN engine build.
    """
    path = os.path.join(root, "runtime", "vm", "thread.h")
    if not os.path.isfile(path):
        log("thread.h not found, skip setjmp patch")
        return
    with open(path, encoding="utf-8") as f:
        s = f.read()
    old = "void* setjmp_function = reinterpret_cast<void*>(&setjmp);"
    new = ("void* setjmp_function = nullptr;  "
           "// FIET: MSVC treats setjmp as a pure intrinsic (no address)")
    if new in s:
        log("thread.h: setjmp address already patched")
        return
    if old not in s:
        log("thread.h: no &setjmp address pattern (ok for non-2.16)")
        return
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(s.replace(old, new, 1))
    log("thread.h: MSVC setjmp-address patch applied (Dart 2.16.x)")

def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    root = os.path.abspath(sys.argv[1])
    if not os.path.isfile(os.path.join(root, "runtime", "vm", "version_in.cc")):
        raise SystemExit(f"not a Dart SDK source tree: {root}")

    version_cc = os.path.join(root, "runtime", "vm", "version.cc")
    if not os.path.isfile(version_cc):
        log("generating runtime/vm/version.cc ...")
        subprocess.run(
            [sys.executable, "tools/make_version.py",
             "--output", "runtime/vm/version.cc",
             "--input", "runtime/vm/version_in.cc"],
            cwd=root, check=True,
        )
    else:
        log("version.cc already present")

    check_cmakelists_patched(root)
    patch_assert_fatal_msvc(root)
    patch_msvc_variadic_macros(root)
    patch_unwinding_records_msvc(root)
    patch_setjmp_address_msvc(root)
    log("done")
    return 0


if __name__ == "__main__":
    sys.exit(main())
