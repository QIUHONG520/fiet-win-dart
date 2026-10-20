cmake_minimum_required(VERSION 3.20)

# fiet-win-dart: Windows x64 Blutter/Dart VM engine DLL.
#
# 由 scripts/build.ps1 调用；输入（-D 缓存变量）：
#   BLUTTER_DIR     上游 worawit/blutter 工作副本（含 blutter/src、scripts、packages、external）
#   DART_VERSION    Dart 版本（默认 3.12.2，与 fler-dart manifest 对齐）
#   DARTVM_LIB      可选：dartvm<ver>_android_arm64.lib 显式路径
#   DART_INCLUDE_DIR 可选：Dart VM 头文件目录
#   CAPSTONE_DIR    blutter/external/capstone（含 include/、capstone.lib、capstone.dll）
#   ICU_LIB         可选：ICU 的 icuuc.lib（默认 blutter/external/icu-windows/lib64）
#   SQLITE_DIR      含 sqlite3.c 的目录（默认仓库 third_party/sqlite）
#   WRAPPER_DIR     仓库 wrapper/ 目录
project(fiet_win_dart LANGUAGES C CXX)

if(NOT BLUTTER_DIR)
    message(FATAL_ERROR "BLUTTER_DIR is required (path to a worawit/blutter checkout)")
endif()
# 允许从 PowerShell/cmd 传 Windows 反斜杠路径（TO_CMAKE_PATH 归一化为 /）。
foreach(_p BLUTTER_DIR DARTVM_LIB DART_INCLUDE_DIR CAPSTONE_DIR ICU_LIB SQLITE_DIR WRAPPER_DIR)
    if(${_p})
        file(TO_CMAKE_PATH "${${_p}}" ${_p})
    endif()
endforeach()
set(DART_VERSION "3.12.2" CACHE STRING "Dart SDK version")
set(_packages "${BLUTTER_DIR}/packages")
set(DARTVM_LIB "${_packages}/lib/dartvm${DART_VERSION}_android_arm64.lib" CACHE FILEPATH "Dart VM static lib")
set(DART_INCLUDE_DIR "${_packages}/include/dartvm${DART_VERSION}" CACHE PATH "Dart VM include dir")
set(CAPSTONE_DIR "${BLUTTER_DIR}/external/capstone" CACHE PATH "Capstone dir")
set(ICU_LIB "${BLUTTER_DIR}/external/icu-windows/lib64/icuuc.lib" CACHE FILEPATH "ICU uc import lib")
set(SQLITE_DIR "${CMAKE_CURRENT_LIST_DIR}/../third_party/sqlite" CACHE PATH "sqlite amalgamation dir")
set(WRAPPER_DIR "${CMAKE_CURRENT_LIST_DIR}/../wrapper" CACHE PATH "wrapper dir")

foreach(required "${DARTVM_LIB}" "${CAPSTONE_DIR}/capstone.lib" "${ICU_LIB}" "${SQLITE_DIR}/sqlite3.c")
    if(NOT EXISTS "${required}")
        message(FATAL_ERROR "missing build input: ${required}")
    endif()
endforeach()

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)
set(CMAKE_POSITION_INDEPENDENT_CODE ON)
if(MSVC)
    # 与 blutter/Dart VM 模板一致：移除 CMake 默认的 /EHsc /GR，改由 target 选项显式控制。
    string(REPLACE "/EHsc" "" CMAKE_CXX_FLAGS "${CMAKE_CXX_FLAGS}")
    string(REPLACE "/GR" "" CMAKE_CXX_FLAGS "${CMAKE_CXX_FLAGS}")
endif()

# ── blutter 源码（排除 main.cpp / pch.cpp；PCH 在 MSVC 下不启用，直接编译源码）
file(GLOB BLUTTER_SRCS CONFIGURE_DEPENDS "${BLUTTER_DIR}/blutter/src/*.cpp")
list(REMOVE_ITEM BLUTTER_SRCS
    "${BLUTTER_DIR}/blutter/src/main.cpp"
    "${BLUTTER_DIR}/blutter/src/pch.cpp")

# ── Dart 版本兼容宏（与 fler-dart build-dartvm.sh Step 2b 同源逻辑）──
# 这些宏影响 blutter 源码对 Dart VM 内部对象布局的解析；按目标 Dart 版本的头文件探测。
set(_vm_inc "${DART_INCLUDE_DIR}/vm")
macro(_dart_head_has OUT FILENAME NEEDLE)
    if(EXISTS "${_vm_inc}/${FILENAME}")
        file(READ "${_vm_inc}/${FILENAME}" _head_content)
        string(FIND "${_head_content}" "${NEEDLE}" _idx)
        if(_idx GREATER -1)
            set(${OUT} TRUE)
        else()
            set(${OUT} FALSE)
        endif()
    else()
        set(${OUT} FALSE)
    endif()
endmacro()

_dart_head_has(_has_linked_hashmap "class_id.h" "V(LinkedHashMap)")
_dart_head_has(_has_immutable_linked_hashmap "class_id.h" "V(ImmutableLinkedHashMap)")
_dart_head_has(_has_last_internal_only_cid "class_id.h" " kLastInternalOnlyCid ")
_dart_head_has(_has_type_ref "class_id.h" "V(TypeRef)")
_dart_head_has(_has_record_type "class_id.h" "V(RecordType)")
_dart_head_has(_has_shared_class_table "class_table.h" "class SharedClassTable {")
_dart_head_has(_has_init_late_static_field "stub_code_list.h" "V(InitLateStaticField)")
_dart_head_has(_has_method_extractor_stub "object_store.h" "build_generic_method_extractor_code)")
_dart_head_has(_has_as_truncated_int64 "object.h" "AsTruncatedInt64Value()")

set(DART_COMPAT_DEFINITIONS)
if(_has_linked_hashmap)
    list(APPEND DART_COMPAT_DEFINITIONS OLD_MAP_SET_NAME)
    if(NOT _has_immutable_linked_hashmap)
        list(APPEND DART_COMPAT_DEFINITIONS OLD_MAP_NO_IMMUTABLE)
    endif()
endif()
if(NOT _has_last_internal_only_cid)
    list(APPEND DART_COMPAT_DEFINITIONS NO_LAST_INTERNAL_ONLY_CID)
endif()
if(_has_type_ref)
    list(APPEND DART_COMPAT_DEFINITIONS HAS_TYPE_REF)
endif()
if(_has_record_type)
    list(APPEND DART_COMPAT_DEFINITIONS HAS_RECORD_TYPE)
endif()
if(_has_shared_class_table)
    list(APPEND DART_COMPAT_DEFINITIONS HAS_SHARED_CLASS_TABLE)
endif()
if(NOT _has_init_late_static_field)
    list(APPEND DART_COMPAT_DEFINITIONS NO_INIT_LATE_STATIC_FIELD)
endif()
if(NOT _has_method_extractor_stub)
    list(APPEND DART_COMPAT_DEFINITIONS NO_METHOD_EXTRACTOR_STUB)
endif()
if(NOT _has_as_truncated_int64)
    list(APPEND DART_COMPAT_DEFINITIONS UNIFORM_INTEGER_ACCESS)
endif()
# Dart 3.13 "single snapshot": OBJECT_STORE_STUB_CODE_LIST removed, VM stubs moved
# to dart::StubCode. patches/patch-blutter-robust.py / prepare_blutter.py provide
# the conditional DartStub/loadStubs implementations behind this macro.
if(DART_VERSION VERSION_GREATER_EQUAL "3.13")
    list(APPEND DART_COMPAT_DEFINITIONS BLUTTER_DART_3_13_SINGLE_SNAPSHOT)
endif()
message(STATUS "Dart ${DART_VERSION} compat defines: ${DART_COMPAT_DEFINITIONS}")

set(COMMON_INCLUDES
    "${BLUTTER_DIR}/blutter/src"
    "${DART_INCLUDE_DIR}"
    "${CAPSTONE_DIR}/include"
    "${CAPSTONE_DIR}/include/capstone"
    "${WRAPPER_DIR}")
set(COMMON_DEFINITIONS
    DART_VERSION="${DART_VERSION}"
    DART_PRECOMPILED_RUNTIME
    DART_TARGET_OS_ANDROID
    TARGET_ARCH_ARM64
    EXCLUDE_CFE_AND_KERNEL_PLATFORM
    PRODUCT
    U_USING_ICU_NAMESPACE=0
    DART_COMPRESSED_POINTERS
    FRIDA_TEMPLATE_DIR="${BLUTTER_DIR}/scripts"
    SQLITE_THREADSAFE=0
    SQLITE_OMIT_LOAD_EXTENSION
    NDEBUG
    _CRT_SECURE_NO_WARNINGS
    ${DART_COMPAT_DEFINITIONS})

# ── CodeAnalyzer 崩溃隔离（SEH）：必须关闭 C++ 异常，单独编译成静态库
add_library(seh_guard STATIC "${WRAPPER_DIR}/seh_guard_win.cpp")
target_include_directories(seh_guard PRIVATE ${COMMON_INCLUDES})
target_compile_definitions(seh_guard PRIVATE ${COMMON_DEFINITIONS})
if(MSVC)
    target_compile_options(seh_guard PRIVATE /EHs-c- /GR- /Zc:preprocessor /utf-8 /O2 /MD /DNDEBUG)
else()
    target_compile_options(seh_guard PRIVATE -fno-exceptions -fno-rtti -O2)
endif()

# ── 引擎 DLL
add_library(engine SHARED
    ${BLUTTER_SRCS}
    "${WRAPPER_DIR}/blutter_entry_win.cpp"
    "${SQLITE_DIR}/sqlite3.c")

target_include_directories(engine PRIVATE ${COMMON_INCLUDES} "${SQLITE_DIR}")
target_compile_definitions(engine PRIVATE ${COMMON_DEFINITIONS})
if(MSVC)
    target_compile_options(engine PRIVATE
        $<$<COMPILE_LANGUAGE:CXX>:/GR-;/EHsc;/Zc:preprocessor;/utf-8;/O2;/MD;/DNDEBUG>
        $<$<COMPILE_LANGUAGE:C>:/O2;/MD;/DNDEBUG>)
else()
    # 保留 POSIX 构建路径（Linux .so）作为参考；官方发布目标仍是 Windows x64。
    target_compile_options(engine PRIVATE $<$<COMPILE_LANGUAGE:CXX>:-O3;-fno-rtti>)
endif()

target_link_libraries(engine PRIVATE
    seh_guard
    "${DARTVM_LIB}"
    "${CAPSTONE_DIR}/capstone.lib"
    "${ICU_LIB}")
if(WIN32)
    target_link_libraries(engine PRIVATE ntdll)
endif()

set_target_properties(engine PROPERTIES
    OUTPUT_NAME "dartvm_${DART_VERSION}_windows_x64"
    PREFIX ""
    SUFFIX ".dll"
    CXX_VISIBILITY_PRESET hidden
    VISIBILITY_INLINES_HIDDEN ON)

# 把运行期依赖复制到输出目录（capstone.dll / ICU），便于直接 LoadLibrary / 打包。
if(WIN32)
    set(RUNTIME_DLLS
        "${CAPSTONE_DIR}/capstone.dll"
        "${BLUTTER_DIR}/external/icu-windows/bin64/icuuc73.dll"
        "${BLUTTER_DIR}/external/icu-windows/bin64/icudt73.dll")
    foreach(dll IN LISTS RUNTIME_DLLS)
        if(EXISTS "${dll}")
            add_custom_command(TARGET engine POST_BUILD
                COMMAND ${CMAKE_COMMAND} -E copy_if_different "${dll}" "$<TARGET_FILE_DIR:engine>")
        endif()
    endforeach()
endif()
