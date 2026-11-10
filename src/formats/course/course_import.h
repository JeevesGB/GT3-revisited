#pragma once

// Import an edited course glTF/GLB (from the Course viewer export) back into a
// game course container. Geometry write-back is in-place so section sizes stay
// identical and the game can load the result.

#include "base/bytes.h"

#include <string>

namespace gt3r::course {

struct CourseImportOptions {
    bool write_road = true;     // GTRW surface verts when counts match / NN map
    bool write_scenery = true;  // GTM1 position UNPACKs (slot 1 and other GTM1s)
    bool z_up_glb = true;       // exported glTF is +Y up facing +Z (engine export)
};

// `original_course` = raw (or gzip-decoded) course container.
// `glb` = binary glTF from Course viewer R2 export / gt3tool.
// Returns a full course container (same structure, updated positions).
Bytes import_course_glb(ByteSpan original_course, ByteSpan glb, const CourseImportOptions& opt = {});

// File helpers: load paths, write out (gzip if out ends with .gz).
std::string import_course_files(const std::string& original_path, const std::string& glb_path,
                                const std::string& out_path, const CourseImportOptions& opt = {});

} // namespace gt3r::course
