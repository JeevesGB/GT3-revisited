#pragma once

// Unpack / pack GT3 course containers (48-slot offset table) for track editing.
// Structure-safe: pack keeps original section sizes when a structure lock is present.

#include "formats/course/course_file.h"

#include <string>
#include <vector>

namespace gt3r::course {

struct CourseBlob {
    int slot = 0;
    std::string tag;
    Bytes data;
};

// Load a course path: auto-detects gzip (standalone .gz dumps) vs raw container.
Bytes load_course_bytes(const std::string& path);

// Write a course path: gzip when path ends in .gz or force_gzip is true.
void save_course_bytes(const std::string& path, ByteSpan raw, bool force_gzip = false);

// Unpack into out_dir:
//   manifest.json, structure_lock.json, blobs/slot_XX_TAG.bin, road/GTRW.bin when present
std::string unpack_course(const std::string& src_path, const std::string& out_dir);

// Pack work folder produced by unpack_course into a game course file.
// Requires structure_lock.json for size checks (game-loadable).
std::string pack_course(const std::string& work_dir, const std::string& out_path);

// Export road mesh from work_dir (or a GTRW.bin path) to a glTF 2.0 + .bin pair.
std::string export_road_gltf(const std::string& gtrw_or_work, const std::string& out_gltf,
                             bool z_up = true);

} // namespace gt3r::course
