#pragma once

// Export / import AI driving lines (course slot 31).

#include "base/bytes.h"
#include "formats/course/ai_lines.h"

#include <string>

namespace gt3r::course {

// Serialize AiLines to a slot-31 section (game layout).
Bytes serialize_ai_lines(const AiLines& lines);

// Minimal JSON: {"build":"...","lines":[{"closed":true,"points":[{"x":..,"z":..,"flags":0,"radius":0,"heading":0,"segment":0},...]},...]}
std::string ai_lines_to_json(const AiLines& lines);
AiLines ai_lines_from_json(const std::string& json);

// File helpers operating on a full course container.
std::string export_ai_json(const std::string& course_path, const std::string& json_path);
std::string import_ai_json(const std::string& course_path, const std::string& json_path,
                           const std::string& out_course_path);

// Replace AI points from a polyline in a GLB (first mesh edges / point list):
// takes successive vertices as control points for line 0.
std::string import_ai_from_glb(const std::string& course_path, const std::string& glb_path,
                               const std::string& out_course_path, int line_index = 0);

} // namespace gt3r::course
