#!/usr/bin/env python3
"""Port fler-dart's Android (POSIX) blutter wrapper to a Windows x64 DLL.

Input : upstream fler-dart dartvm/src/blutter_entry.cpp (pinned copy in this repo)
Output: wrapper/blutter_entry_win.cpp with Windows-specific replacements:
  - POSIX headers -> Win32 headers (conditional, POSIX path kept for reference)
  - mkdtemp/opendir/readdir/unlink -> Win32 temp dir + std::filesystem::remove_all
  - sigaction/sigsetjmp crash isolation -> SEH guard (wrapper/seh_guard_win.cpp)
  - __attribute__((visibility)) -> __declspec(dllexport)
  - extra export: fler_engine_info()

Usage: python scripts/port_wrapper.py <fler-dart>/dartvm/src/blutter_entry.cpp <out.cpp>
"""
import io
import sys
import textwrap

# 1) POSIX headers -> conditional headers
OLD_INC = """#include <cinttypes>
#include <csetjmp>
#include <csignal>
#include <filesystem>

#include <unistd.h>
#include <sys/stat.h>
#include <dirent.h>
"""
NEW_INC = """#include <cinttypes>
#include <filesystem>

#if defined(_WIN32)
#  include <windows.h>
#  include <io.h>
#  include <direct.h>
#  include <sys/stat.h>
#else
#  include <csetjmp>
#  include <csignal>
#  include <unistd.h>
#  include <sys/stat.h>
#  include <dirent.h>
#endif
"""

# 2) POSIX-only csetjmp crash handler -> wrap in #if !defined(_WIN32)
CRASH_START = "namespace {\n// 注意：不能用 thread_local！"
CRASH_END = "} // namespace\n"

# 3) temp dir helpers -> Win32 implementation (POSIX kept under #else)
TEMP_FUNCS = """// ─── Temp dir helpers ──────────────────────────
static bool createTempDir(char* buf, size_t sz) {
#if defined(_WIN32)
    // Windows DLL: GetTempPathW + GetTempFileNameW(0) 只用来取唯一名字，随后删文件建目录。
    wchar_t wtmp[MAX_PATH] = {};
    const DWORD n = GetTempPathW(MAX_PATH, wtmp);
    if (n == 0 || n >= MAX_PATH) return false;
    for (int attempt = 0; attempt < 100; ++attempt) {
        wchar_t wname[MAX_PATH] = {};
        if (GetTempFileNameW(wtmp, L"flr", 0, wname) == 0) continue;
        DeleteFileW(wname);
        if (!CreateDirectoryW(wname, nullptr)) continue;
        const int len = WideCharToMultiByte(CP_UTF8, 0, wname, -1, buf, (int)sz, nullptr, nullptr);
        if (len > 0 && (size_t)len <= sz) return true;
        RemoveDirectoryW(wname);
    }
    return false;
#else
    // 优先用 TMPDIR（bridge 会 chdir + setenv 到 App 可写目录，避免 /data/local/tmp 不可写）
    const char* tmp = getenv("TMPDIR");
    if (tmp && tmp[0]) {
        std::string tmpl = std::string(tmp) + "/fler_XXXXXX";
        if (sz >= tmpl.size() + 1) {
            strncpy(buf, tmpl.c_str(), sz);
            if (mkdtemp(buf) != nullptr) return true;
        }
    }
    const char* tmpl = "/data/local/tmp/fler_XXXXXX";
    if (sz < strlen(tmpl) + 1) return false;
    strncpy(buf, tmpl, sz);
    if (mkdtemp(buf) == nullptr) {
        const char* alt = "/tmp/fler_XXXXXX";
        strncpy(buf, alt, sz);
        if (mkdtemp(buf) == nullptr) return false;
    }
    return true;
#endif
}

static void removeDir(const char* path) {
#if defined(_WIN32)
    if (!path || !path[0]) return;
    const int wlen = MultiByteToWideChar(CP_UTF8, 0, path, -1, nullptr, 0);
    if (wlen <= 0) return;
    std::wstring wpath(static_cast<size_t>(wlen), L'\\0');
    MultiByteToWideChar(CP_UTF8, 0, path, -1, &wpath[0], wlen);
    std::error_code ec;
    std::filesystem::remove_all(std::filesystem::path(wpath), ec);
#else
    DIR* d = opendir(path); if (!d) return;
    struct dirent* e;
    while ((e = readdir(d)) != nullptr) {
        std::string n(e->d_name);
        if (n == "." || n == "..") continue;
        std::string f = std::string(path) + "/" + n;
        if (e->d_type == DT_DIR) removeDir(f.c_str());
        else unlink(f.c_str());
    }
    closedir(d); rmdir(path);
#endif
}
"""

# 4) crash isolation block replacement (POSIX sigaction -> Windows SEH helper)
OLD_CA_START = """#ifndef NO_CODE_ANALYSIS
        {
            // 隔离 CodeAnalyzer：崩溃则降级为只导出不反汇编（见 caCrashHandler）。
            struct sigaction sa;"""
NEW_CA_WIN = """#ifndef NO_CODE_ANALYSIS
#if defined(_WIN32)
        {
            // Windows: 用 SEH（wrapper/seh_guard_win.cpp）隔离 CodeAnalyzer；
            // 崩溃则降级为「只导出不反汇编」，与 Android 的 sigaction 降级语义一致。
            // 崩溃后【不】调用 ExitScope（Dart isolate 状态可能已损坏），保持 inScope 幂等标志，
            // 后续导出按 GetAnalyzedData()==null 自动退化。
            app.EnterScope();
            const int ca_seh_rc = fler_run_code_analysis_guarded(&app);
            if (ca_seh_rc == 0) {
                app.ExitScope();
            } else {
                fprintf(stderr,
                        "fler-dart: CodeAnalyzer crashed (SEH rc=%d), fallback to no-analysis export\\n",
                        ca_seh_rc);
            }
        }
#else
        {
            // 隔离 CodeAnalyzer：崩溃则降级为只导出不反汇编（见 caCrashHandler）。
            struct sigaction sa;"""

OLD_CA_END = """            sigaction(SIGILL, &old_ill, nullptr);
        }
#endif
        fprintf(stderr, "fler-dart: stage=open-database\\n");"""
NEW_CA_END = """            sigaction(SIGILL, &old_ill, nullptr);
        }
#endif  // _WIN32
#endif
        fprintf(stderr, "fler-dart: stage=open-database\\n");"""

EXPORT_DECL = """extern "C" __attribute__((visibility("default")))
int blutter_analyze(const char* so_path, const char* db_path, const char* out_dir) {"""
EXPORT_REPL = """FLER_DART_EXPORT int blutter_analyze(const char* so_path, const char* db_path, const char* out_dir) {"""

EXPORT_MACRO = """// ─── Windows DLL export ───────────────────────
#if defined(_WIN32)
#  define FLER_DART_EXPORT extern "C" __declspec(dllexport)
#else
#  define FLER_DART_EXPORT extern "C" __attribute__((visibility("default")))
#endif

#if defined(_WIN32)
// 由 wrapper/seh_guard_win.cpp 提供（编译时关闭 C++ 异常，仅用 SEH 捕获硬件异常）。
extern "C" int fler_run_code_analysis_guarded(void* app);
#endif

"""


def main() -> int:
    if len(sys.argv) != 3:
        print(__doc__)
        return 2
    src, out = sys.argv[1], sys.argv[2]
    s = io.open(src, encoding="utf-8").read()

    def replace_once(old, new, what):
        nonlocal s
        if old not in s:
            raise SystemExit(f"pattern not found: {what}")
        s = s.replace(old, new, 1)

    replace_once(OLD_INC, NEW_INC, "POSIX includes")
    i = s.index(CRASH_START)
    j = s.index(CRASH_END, i) + len(CRASH_END)
    s = s[:i] + "#if !defined(_WIN32)\n" + s[i:j] + "#endif  // !_WIN32\n" + s[j:]

    # temp dir helpers: replace from marker to the exported-entry comment marker
    m0 = s.index("// ─── Temp dir helpers ──")
    m1 = s.index("// ─── Exported entry point ──")
    s = s[:m0] + TEMP_FUNCS + "\n" + s[m1:]

    replace_once(OLD_CA_START, NEW_CA_WIN, "CodeAnalyzer isolation start")
    replace_once(OLD_CA_END, NEW_CA_END, "CodeAnalyzer isolation end")
    replace_once(EXPORT_DECL, EXPORT_MACRO + EXPORT_REPL, "export declaration")

    # extra exported diagnostics helper at the end of file
    s = s.rstrip() + textwrap.dedent(
        """

        // ─── Engine metadata (Windows) ─────────────
        // 供宿主（FIET）探测引擎版本与构建目标，不参与分析流程。
        FLER_DART_EXPORT const char* fler_engine_info() {
            return "fiet-win-dart 0.1.0; dart=3.12.2; target=android_arm64; host=windows_x64; "
                   "exports=blutter_analyze,fler_engine_info";
        }
        """
    )
    io.open(out, "w", encoding="utf-8", newline="\n").write(s)
    print(f"ported wrapper -> {out} ({len(s.splitlines())} lines)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
