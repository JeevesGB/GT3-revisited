#include "formats/course/course_import.h"

#include "base/file.h"
#include "base/gzip.h"
#include "formats/course/course_file.h"
#include "formats/course/course_pack.h"
#include "formats/course/road.h"
#include "formats/model/gltf.h"

#include <cmath>
#include <cstring>
#include <sstream>
#include <vector>

namespace gt3r::course {
namespace {

struct Pos {
    float x, y, z;
};

struct PosOff {
    size_t ox, oy, oz;
};

void wr_f32(u8* base, size_t off, float v) { std::memcpy(base + off, &v, 4); }
float rd_f32(const u8* base, size_t off) {
    float v;
    std::memcpy(&v, base + off, 4);
    return v;
}
u32 rd32u(const u8* p) {
    u32 v;
    std::memcpy(&v, p, 4);
    return v;
}

// Only 1:1 count mapping — nearest-neighbour on 200k+ verts freezes the UI.
size_t write_gtrw_positions(Bytes& gtrw, const std::vector<Pos>& positions) {
    if (gtrw.size() < 0x60 || std::memcmp(gtrw.data(), "GTRW", 4) != 0)
        throw FormatError("not GTRW");
    Road road = Road::parse(gtrw);
    size_t need = 0;
    for (const auto& s : road.segments) need += s.vertices.size();
    if (positions.size() != need) {
        // Not a road-sized mesh (typical course export is scenery). Skip quietly.
        return 0;
    }
    u32 nseg = rd32u(gtrw.data() + 0x30);
    u32 seg_off = rd32u(gtrw.data() + 0x34);
    size_t vi = 0;
    for (u32 i = 0; i < nseg; ++i) {
        size_t s = size_t(seg_off) + size_t(i) * 0x40;
        u16 nv = u16(gtrw[s] | (gtrw[s + 1] << 8));
        u32 voff = rd32u(gtrw.data() + s + 4);
        for (u16 k = 0; k < nv; ++k) {
            size_t o = size_t(voff) + size_t(k) * 16;
            wr_f32(gtrw.data(), o, positions[vi].x);
            wr_f32(gtrw.data(), o + 4, positions[vi].y);
            wr_f32(gtrw.data(), o + 8, positions[vi].z);
            ++vi;
        }
    }
    return vi;
}

static int vif_unpack_bytes(int vn, int vl, int count) {
    if (vn == 3 && vl == 3) return count * 2;
    int bits = (vl == 0 ? 32 : vl == 1 ? 16 : vl == 2 ? 8 : 5);
    int comps = vn + 1;
    int raw = (count * comps * bits) / 8;
    return (raw + 3) & ~3;
}

// Collect V3-32 @ addr 0 UNPACK payloads. Walk by 4 bytes but skip consumed payloads.
std::vector<PosOff> collect_gtm1_pos_offsets(ByteSpan gtm1) {
    std::vector<PosOff> out;
    if (gtm1.size() < 16 || std::memcmp(gtm1.data(), "GTM1", 4) != 0) return out;
    for (size_t o = 16; o + 8 < gtm1.size();) {
        u32 code = rd32u(gtm1.data() + o);
        u32 cmd = (code >> 24) & 0x7f;
        if ((cmd & 0x60) != 0x60) {
            o += 4;
            continue;
        }
        int vn = int((cmd >> 2) & 3);
        int vl = int(cmd & 3);
        int num = int((code >> 16) & 0xff);
        int count = num ? num : 256;
        int addr = int(code & 0x3ff);
        int len = vif_unpack_bytes(vn, vl, count);
        size_t payload = o + 4;
        if (payload + size_t(len) > gtm1.size()) {
            o += 4;
            continue;
        }
        if (addr == 0x00 && vn == 2 && vl == 0 && count > 0 && count < 4096) {
            bool ok = true;
            for (int i = 0; i < count && ok; ++i) {
                float x = rd_f32(gtm1.data(), payload + size_t(i) * 16);
                float y = rd_f32(gtm1.data(), payload + size_t(i) * 16 + 4);
                float z = rd_f32(gtm1.data(), payload + size_t(i) * 16 + 8);
                if (!std::isfinite(x) || !std::isfinite(y) || !std::isfinite(z)) ok = false;
                if (std::fabs(x) > 50000.f || std::fabs(y) > 50000.f || std::fabs(z) > 50000.f) ok = false;
            }
            if (ok) {
                for (int i = 0; i < count; ++i) {
                    size_t b = payload + size_t(i) * 16;
                    out.push_back({b, b + 4, b + 8});
                }
            }
        }
        o = payload + size_t(len);
    }
    return out;
}

size_t write_gtm1_positions(Bytes& gtm1, const std::vector<Pos>& positions) {
    auto offs = collect_gtm1_pos_offsets(gtm1);
    if (offs.empty()) return 0;
    // Require exact count — NN would hang on large courses.
    if (positions.size() != offs.size()) return 0;
    for (size_t i = 0; i < offs.size(); ++i) {
        wr_f32(gtm1.data(), offs[i].ox, positions[i].x);
        wr_f32(gtm1.data(), offs[i].oy, positions[i].y);
        wr_f32(gtm1.data(), offs[i].oz, positions[i].z);
    }
    return offs.size();
}

std::vector<Pos> model_positions(const scene::Model& model) {
    std::vector<Pos> out;
    for (const scene::Mesh& mesh : model.meshes)
        for (const scene::Vertex& v : mesh.vertices) out.push_back({v.pos[0], v.pos[1], v.pos[2]});
    return out;
}

} // namespace

Bytes import_course_glb(ByteSpan original_course, ByteSpan glb, const CourseImportOptions& opt) {
    CourseFile file = CourseFile::parse(original_course);
    scene::Model model = load_glb(glb, {}, "course_import");
    std::vector<Pos> positions = model_positions(model);
    if (positions.empty()) throw FormatError("GLB has no vertices");

    Bytes out(original_course.size());
    std::memcpy(out.data(), original_course.data(), original_course.size());

    size_t road_n = 0, scen_n = 0;

    if (opt.write_road) {
        if (const CourseSection* s = file.find(kSlotRoad)) {
            Bytes section(s->size);
            std::memcpy(section.data(), out.data() + s->offset, s->size);
            road_n = write_gtrw_positions(section, positions);
            if (road_n) std::memcpy(out.data() + s->offset, section.data(), section.size());
        }
    }

    if (opt.write_scenery) {
        // Prefer main scenery (slot 1) first when counts match that block alone.
        for (const CourseSection& s : file.sections()) {
            if (s.size < 4) continue;
            if (std::memcmp(original_course.data() + s.offset, "GTM1", 4) != 0) continue;
            Bytes section(s.size);
            std::memcpy(section.data(), out.data() + s.offset, s.size);
            size_t n = write_gtm1_positions(section, positions);
            if (n) {
                std::memcpy(out.data() + s.offset, section.data(), section.size());
                scen_n += n;
                // Course viewer export is typically one merged model → one matching GTM1.
                break;
            }
        }
    }

    if (road_n == 0 && scen_n == 0) {
        throw FormatError(
            "vertex count does not match road or scenery (export from Course viewer, edit positions only, re-export GLB)");
    }

    CourseFile::parse(out);
    return out;
}

std::string import_course_files(const std::string& original_path, const std::string& glb_path,
                                const std::string& out_path, const CourseImportOptions& opt) {
    Bytes course = load_course_bytes(original_path);
    auto glb = read_host_file(glb_path);
    if (!glb) throw FormatError("cannot read " + glb_path);
    Bytes packed = import_course_glb(course, *glb, opt);
    if (packed.size() != course.size()) throw FormatError("import changed course size — refused");
    save_course_bytes(out_path, packed, false);
    std::ostringstream msg;
    msg << "imported " << glb_path << " -> " << out_path << " (" << packed.size() << " bytes)";
    return msg.str();
}

} // namespace gt3r::course
