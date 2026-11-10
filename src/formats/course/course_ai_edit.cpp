#include "formats/course/course_ai_edit.h"

#include "base/file.h"
#include "formats/course/course_file.h"
#include "formats/course/course_pack.h"
#include "formats/model/gltf.h"

#include <cmath>
#include <cstdio>
#include <cstring>
#include <numbers>
#include <sstream>

namespace gt3r::course {
namespace {

void w32(Bytes& b, size_t off, u32 v) {
    if (off + 4 > b.size()) b.resize(off + 4);
    std::memcpy(b.data() + off, &v, 4);
}
void append_u32(Bytes& b, u32 v) {
    size_t o = b.size();
    b.resize(o + 4);
    std::memcpy(b.data() + o, &v, 4);
}
void append_s32(Bytes& b, s32 v) { append_u32(b, u32(v)); }

std::string json_escape(const std::string& s) {
    std::string o;
    for (char c : s) {
        if (c == '"' || c == '\\') o.push_back('\\');
        o.push_back(c);
    }
    return o;
}

// Very small JSON number extractor
double json_num_after(const std::string& j, size_t pos) {
    while (pos < j.size() && (j[pos] == ' ' || j[pos] == ':' || j[pos] == ',')) ++pos;
    return std::atof(j.c_str() + pos);
}

} // namespace

Bytes serialize_ai_lines(const AiLines& lines) {
    Bytes out(0x48, 0);
    w32(out, 4, 8);
    // build stamp
    std::string build = lines.build.empty() ? "build GT3R\n" : lines.build;
    for (size_t i = 0; i < build.size() && 0x28 + i < 0x48; ++i) out[0x28 + i] = u8(build[i]);

    std::array<u32, 7> offs{};
    for (int li = 0; li < 7; ++li) {
        if (li >= int(lines.lines.size()) || lines.lines[size_t(li)].points.empty()) {
            offs[size_t(li)] = 0;
            continue;
        }
        while (out.size() % 4) out.push_back(0);
        offs[size_t(li)] = u32(out.size());
        const AiLine& line = lines.lines[size_t(li)];
        append_u32(out, u32(line.points.size()));
        for (const AiPoint& pt : line.points) {
            // world x -> sim x mirrored
            s32 rx = pt.raw_x ? pt.raw_x : s32(std::lround(-pt.pos.x * 4096.0f));
            s32 rz = pt.raw_z ? pt.raw_z : s32(std::lround(pt.pos.z * 4096.0f));
            s32 rr = pt.raw_radius ? pt.raw_radius : s32(std::lround(pt.lateral * 4096.0f));
            u32 packed = pt.packed;
            if (!packed) {
                // heading world -> sim (negate)
                float turns = -pt.heading / float(2 * std::numbers::pi);
                s16 h = s16(std::lround(turns * 4096.0f));
                packed = u32(u16(h));
            }
            append_u32(out, pt.flags);
            append_s32(out, rx);
            append_s32(out, rz);
            append_u32(out, 0);
            append_u32(out, pt.segment);
            append_u32(out, 0);
            append_s32(out, rr);
            append_u32(out, 0);
            append_u32(out, 0);
            append_u32(out, packed);
        }
    }
    for (int li = 0; li < 7; ++li) w32(out, 0x0C + 4 * size_t(li), offs[size_t(li)]);
    w32(out, 0, u32(out.size()));
    // Round-trip validate
    AiLines::parse(out);
    return out;
}

std::string ai_lines_to_json(const AiLines& lines) {
    std::ostringstream o;
    o << "{\n  \"build\": \"" << json_escape(lines.build) << "\",\n  \"lines\": [\n";
    for (size_t li = 0; li < lines.lines.size(); ++li) {
        const AiLine& line = lines.lines[li];
        o << "    {\"closed\": " << (line.closed ? "true" : "false") << ", \"points\": [";
        for (size_t i = 0; i < line.points.size(); ++i) {
            const AiPoint& p = line.points[i];
            if (i) o << ", ";
            o << "{\"x\":" << p.pos.x << ",\"y\":" << p.pos.y << ",\"z\":" << p.pos.z
              << ",\"flags\":" << p.flags << ",\"radius\":" << p.lateral << ",\"heading\":" << p.heading
              << ",\"segment\":" << p.segment << "}";
        }
        o << "]}";
        if (li + 1 < lines.lines.size()) o << ",";
        o << "\n";
    }
    o << "  ]\n}\n";
    return o.str();
}

AiLines ai_lines_from_json(const std::string& json) {
    AiLines out;
    size_t b = json.find("\"build\"");
    if (b != std::string::npos) {
        size_t q0 = json.find('"', json.find(':', b) + 1);
        size_t q1 = json.find('"', q0 + 1);
        if (q0 != std::string::npos && q1 != std::string::npos) out.build = json.substr(q0 + 1, q1 - q0 - 1);
    }
    size_t pos = 0;
    while (out.lines.size() < 7) {
        size_t lp = json.find("\"points\"", pos);
        if (lp == std::string::npos) break;
        AiLine line;
        size_t lb = json.find('[', lp);
        size_t le = json.find(']', lb);
        if (lb == std::string::npos || le == std::string::npos) break;
        size_t p = lb;
        while ((p = json.find("\"x\"", p)) != std::string::npos && p < le) {
            AiPoint pt;
            pt.pos.x = float(json_num_after(json, json.find(':', p) + 1));
            size_t yk = json.find("\"y\"", p);
            if (yk != std::string::npos && yk < le) pt.pos.y = float(json_num_after(json, json.find(':', yk) + 1));
            size_t zk = json.find("\"z\"", p);
            if (zk != std::string::npos && zk < le) pt.pos.z = float(json_num_after(json, json.find(':', zk) + 1));
            size_t fk = json.find("\"flags\"", p);
            if (fk != std::string::npos && fk < le) pt.flags = u32(json_num_after(json, json.find(':', fk) + 1));
            size_t rk = json.find("\"radius\"", p);
            if (rk != std::string::npos && rk < le) {
                pt.lateral = float(json_num_after(json, json.find(':', rk) + 1));
                if (pt.lateral != 0) pt.flags |= 1;
            }
            size_t hk = json.find("\"heading\"", p);
            if (hk != std::string::npos && hk < le) pt.heading = float(json_num_after(json, json.find(':', hk) + 1));
            size_t sk = json.find("\"segment\"", p);
            if (sk != std::string::npos && sk < le) pt.segment = u32(json_num_after(json, json.find(':', sk) + 1));
            line.points.push_back(pt);
            p = json.find('}', p) + 1;
        }
        if (line.points.size() >= 4) {
            const Vec3& p0 = line.points.front().pos;
            const Vec3& p1 = line.points.back().pos;
            line.closed = std::hypot(p0.x - p1.x, p0.z - p1.z) < 250.0f;
        }
        out.lines.push_back(std::move(line));
        pos = le + 1;
    }
    while (out.lines.size() < 7) out.lines.push_back({});
    return out;
}

static Bytes replace_slot(ByteSpan course, int slot, ByteSpan section) {
    CourseFile file = CourseFile::parse(course);
    std::vector<Bytes> payloads(kSlotCount);
    for (const CourseSection& s : file.sections()) {
        Bytes chunk(s.size);
        std::memcpy(chunk.data(), course.data() + s.offset, s.size);
        payloads[size_t(s.slot)] = std::move(chunk);
    }
    payloads[size_t(slot)].assign(section.begin(), section.end());
    Bytes table(size_t(kSlotCount) * 4, 0);
    Bytes body;
    u32 cursor = u32(kSlotCount * 4);
    for (int s = 0; s < kSlotCount; ++s) {
        if (payloads[size_t(s)].empty()) continue;
        std::memcpy(table.data() + s * 4, &cursor, 4);
        body.insert(body.end(), payloads[size_t(s)].begin(), payloads[size_t(s)].end());
        cursor += u32(payloads[size_t(s)].size());
    }
    Bytes raw;
    raw.insert(raw.end(), table.begin(), table.end());
    raw.insert(raw.end(), body.begin(), body.end());
    CourseFile::parse(raw);
    return raw;
}

std::string export_ai_json(const std::string& course_path, const std::string& json_path) {
    Bytes course = load_course_bytes(course_path);
    CourseFile file = CourseFile::parse(course);
    ByteSpan sec = file.section(course, kSlotAiLines);
    if (sec.empty()) throw FormatError("course has no AI lines section");
    AiLines lines = AiLines::parse(sec);
    std::string json = ai_lines_to_json(lines);
    write_host_file(json_path, ByteSpan{reinterpret_cast<const u8*>(json.data()), json.size()});
    return "exported AI lines -> " + json_path;
}

std::string import_ai_json(const std::string& course_path, const std::string& json_path,
                           const std::string& out_course_path) {
    Bytes course = load_course_bytes(course_path);
    auto js = read_host_file(json_path);
    if (!js) throw FormatError("cannot read " + json_path);
    std::string json(reinterpret_cast<const char*>(js->data()), js->size());
    AiLines lines = ai_lines_from_json(json);
    Bytes section = serialize_ai_lines(lines);
    Bytes packed = replace_slot(course, kSlotAiLines, section);
    save_course_bytes(out_course_path, packed, false);
    return "imported AI JSON -> " + out_course_path;
}

std::string import_ai_from_glb(const std::string& course_path, const std::string& glb_path,
                               const std::string& out_course_path, int line_index) {
    Bytes course = load_course_bytes(course_path);
    auto glb = read_host_file(glb_path);
    if (!glb) throw FormatError("cannot read " + glb_path);
    scene::Model model = load_glb(*glb, {}, "ai_line");
    std::vector<Vec3> pts;
    for (const scene::Mesh& m : model.meshes) {
        for (const scene::Vertex& v : m.vertices) pts.push_back({v.pos[0], v.pos[1], v.pos[2]});
        if (!pts.empty()) break;
    }
    if (pts.size() < 2) throw FormatError("GLB has no polyline vertices");

    CourseFile file = CourseFile::parse(course);
    ByteSpan sec = file.section(course, kSlotAiLines);
    AiLines lines = sec.empty() ? AiLines{} : AiLines::parse(sec);
    while (lines.lines.size() < 7) lines.lines.push_back({});
    if (line_index < 0 || line_index > 6) line_index = 0;
    AiLine& line = lines.lines[size_t(line_index)];
    line.points.clear();
    for (const Vec3& v : pts) {
        AiPoint p;
        p.pos = v;
        line.points.push_back(p);
    }
    if (line.points.size() >= 4) {
        const Vec3& p0 = line.points.front().pos;
        const Vec3& p1 = line.points.back().pos;
        line.closed = std::hypot(p0.x - p1.x, p0.z - p1.z) < 250.0f;
    }
    Bytes section = serialize_ai_lines(lines);
    Bytes packed = replace_slot(course, kSlotAiLines, section);
    save_course_bytes(out_course_path, packed, false);
    return "imported AI line from GLB -> " + out_course_path;
}

} // namespace gt3r::course
