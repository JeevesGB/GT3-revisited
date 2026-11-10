// gt3tool — command-line utilities for GT3 Revisited.

#include "formats/course/course_file.h"
#include "formats/course/course_import.h"
#include "formats/course/course_rebuild.h"
#include "formats/course/course_ai_edit.h"
#include "formats/course/course_pack.h"

#include <cstdio>
#include <exception>
#include <string>

using namespace gt3r;
using namespace gt3r::course;

static int usage() {
    std::fprintf(stderr,
                 "gt3tool — GT3 Revisited utilities\n\n"
                 "Course import (edited GLB from Course viewer R2 export):\n"
                 "  gt3tool course import  <original.gz|bin> <edited.glb> <out.gz|bin>\n\n"
                 "Also:\n"
                 "  gt3tool course info    <course>\n"
                 "  gt3tool course extract <course> <out_dir>\n"
                 "  gt3tool course pack    <work_dir> <out>\n"
                 "  gt3tool course gltf    <work_dir|GTRW.bin> <out.gltf>\n                 "  gt3tool course rebuild-road <original> <road.glb> <out>\n                 "  gt3tool course ai-export   <course> <out.json>\n                 "  gt3tool course ai-import   <course> <in.json> <out>\n                 "  gt3tool course ai-from-glb <course> <line.glb> <out> [lineIndex]\n\n"
                 "Import writes positions back into GTRW/GTM1 in-place (same section sizes).\n");
    return 2;
}

static int course_info(const std::string& path) {
    Bytes data = load_course_bytes(path);
    CourseFile f = CourseFile::parse(data);
    std::printf("file: %s\nraw_size: %zu\nsections: %zu\n", path.c_str(), data.size(), f.sections().size());
    for (const CourseSection& s : f.sections())
        std::printf("  slot %2d  %-4s  %9u B\n", s.slot, s.tag.empty() ? "-" : s.tag.c_str(), s.size);
    return 0;
}

int main(int argc, char** argv) {
    if (argc < 2) return usage();
    try {
        if (std::string(argv[1]) != "course" || argc < 3) return usage();
        std::string cmd = argv[2];
        if (cmd == "info" && argc >= 4) return course_info(argv[3]);
        if (cmd == "extract" && argc >= 5) {
            std::puts(unpack_course(argv[3], argv[4]).c_str());
            try {
                std::puts(export_road_gltf(argv[4], std::string(argv[4]) + "/blender/road.gltf", true).c_str());
            } catch (const std::exception& e) {
                std::printf("gltf: %s\n", e.what());
            }
            return 0;
        }
        if (cmd == "pack" && argc >= 5) {
            std::puts(pack_course(argv[3], argv[4]).c_str());
            return 0;
        }
        if (cmd == "gltf" && argc >= 5) {
            std::puts(export_road_gltf(argv[3], argv[4], true).c_str());
            return 0;
        }
        if (cmd == "import" && argc >= 6) {
            CourseImportOptions opt;
            std::puts(import_course_files(argv[3], argv[4], argv[5], opt).c_str());
            return 0;
        }
        if (cmd == "rebuild-road" && argc >= 6) {
            RoadRebuildOptions opt;
            std::puts(rebuild_course_road_files(argv[3], argv[4], argv[5], opt).c_str());
            return 0;
        }
        if (cmd == "ai-export" && argc >= 5) {
            std::puts(export_ai_json(argv[3], argv[4]).c_str());
            return 0;
        }
        if (cmd == "ai-import" && argc >= 6) {
            std::puts(import_ai_json(argv[3], argv[4], argv[5]).c_str());
            return 0;
        }
        if (cmd == "ai-from-glb" && argc >= 6) {
            int li = argc >= 7 ? std::atoi(argv[6]) : 0;
            std::puts(import_ai_from_glb(argv[3], argv[4], argv[5], li).c_str());
            return 0;
        }
        return usage();
    } catch (const std::exception& e) {
        std::fprintf(stderr, "error: %s\n", e.what());
        return 1;
    }
}
