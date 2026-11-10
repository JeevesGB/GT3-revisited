#pragma once

// Rebuild course sections from edited meshes (new binary data, not in-place patch).

#include "base/bytes.h"

#include <string>

namespace gt3r::course {

struct RoadRebuildOptions {
    bool keep_template_checkpoints = true;
    bool keep_template_walls = true;
    bool keep_template_grid_slots = true; // start grid poses
    bool keep_template_markers = true;
    // When true (and keep_template_* is false, or template empty), derive from mesh:
    bool generate_walls_from_boundary = true;
    bool generate_checkpoints = false; // sample strips across the mesh
    int checkpoint_count = 32;
    float default_length = 0; // 0 = keep template length or estimate from mesh
};

// Build a new GTRW section from a triangle mesh (game Y-up positions).
// `template_gtrw` supplies course id, length, and optional checkpoint/wall/grid data.
Bytes rebuild_gtrw_from_mesh(ByteSpan template_gtrw,
                             const float* positions, size_t vertex_count, // xyz tightly packed
                             const u32* indices, size_t index_count,      // triangles as a,b,c
                             const RoadRebuildOptions& opt = {});

// Load original course + GLB, replace slot 28 with rebuilt GTRW, return full container.
Bytes rebuild_course_road_from_glb(ByteSpan original_course, ByteSpan glb,
                                   const RoadRebuildOptions& opt = {});

// File helper.
std::string rebuild_course_road_files(const std::string& original_path, const std::string& glb_path,
                                      const std::string& out_path, const RoadRebuildOptions& opt = {});

} // namespace gt3r::course
