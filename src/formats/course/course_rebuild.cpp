#include "formats/course/course_rebuild.h"

#include "base/file.h"
#include "formats/course/course_file.h"
#include "formats/course/course_pack.h"
#include "formats/course/road.h"
#include "formats/model/gltf.h"

#include <algorithm>
#include <cmath>
#include <cstring>
#include <map>
#include <sstream>
#include <unordered_map>
#include <vector>

namespace gt3r::course {
namespace {

void w32(Bytes& buf, size_t off, u32 v) {
    if (off + 4 > buf.size()) buf.resize(off + 4);
    std::memcpy(buf.data() + off, &v, 4);
}
void w16(Bytes& buf, size_t off, u16 v) {
    if (off + 2 > buf.size()) buf.resize(off + 2);
    std::memcpy(buf.data() + off, &v, 2);
}
void wf(Bytes& buf, size_t off, float v) {
    u32 u;
    std::memcpy(&u, &v, 4);
    w32(buf, off, u);
}
void append_bytes(Bytes& buf, const void* p, size_t n) {
    const u8* s = static_cast<const u8*>(p);
    buf.insert(buf.end(), s, s + n);
}
u32 rd32u(const u8* p) {
    u32 v;
    std::memcpy(&v, p, 4);
    return v;
}

struct SegMesh {
    std::vector<float> pos; // xyz tightly packed
    std::vector<u16> idx;   // triangle list
};

// Split a large mesh into GTRW segments (max 65535 verts / 65535 tris each).
std::vector<SegMesh> split_into_segments(const float* positions, size_t vertex_count, const u32* indices,
                                         size_t index_count) {
    constexpr size_t kMaxV = 65535;
    constexpr size_t kMaxT = 65535;
    std::vector<SegMesh> segs;
    SegMesh cur;
    std::unordered_map<u32, u16> g2l;
    g2l.reserve(4096);

    auto flush = [&] {
        if (!cur.idx.empty()) segs.push_back(std::move(cur));
        cur = SegMesh{};
        g2l.clear();
    };

    auto ensure_vert = [&](u32 g) -> u16 {
        auto it = g2l.find(g);
        if (it != g2l.end()) return it->second;
        if (cur.pos.size() / 3 >= kMaxV) return u16(0xFFFF); // signal full
        u16 loc = static_cast<u16>(cur.pos.size() / 3);
        cur.pos.push_back(positions[g * 3 + 0]);
        cur.pos.push_back(positions[g * 3 + 1]);
        cur.pos.push_back(positions[g * 3 + 2]);
        g2l.emplace(g, loc);
        return loc;
    };

    const size_t tri_count = index_count / 3;
    for (size_t t = 0; t < tri_count; ++t) {
        u32 ga = indices[t * 3 + 0], gb = indices[t * 3 + 1], gc = indices[t * 3 + 2];
        if (ga >= vertex_count || gb >= vertex_count || gc >= vertex_count) continue;

        // How many new verts would this triangle need?
        size_t need_new = 0;
        for (u32 g : {ga, gb, gc})
            if (!g2l.count(g)) ++need_new;
        if (cur.pos.size() / 3 + need_new > kMaxV || cur.idx.size() / 3 >= kMaxT) flush();

        u16 la = ensure_vert(ga), lb = ensure_vert(gb), lc = ensure_vert(gc);
        if (la == 0xFFFF || lb == 0xFFFF || lc == 0xFFFF) {
            flush();
            la = ensure_vert(ga);
            lb = ensure_vert(gb);
            lc = ensure_vert(gc);
        }
        cur.idx.push_back(la);
        cur.idx.push_back(lb);
        cur.idx.push_back(lc);
    }
    flush();
    if (segs.empty()) throw FormatError("rebuild-road: no triangles after split");
    if (segs.size() > 65535) throw FormatError("rebuild-road: too many segments");
    return segs;
}

std::vector<WallPoint> walls_from_boundary(const float* pos, size_t nv, const u32* idx, size_t ni) {
    struct EdgeKey {
        u32 a, b;
        bool operator<(const EdgeKey& o) const { return a < o.a || (a == o.a && b < o.b); }
    };
    auto canon = [](u32 i, u32 j) { return EdgeKey{std::min(i, j), std::max(i, j)}; };
    std::map<EdgeKey, int> count;
    for (size_t t = 0; t + 2 < ni; t += 3) {
        u32 ia = idx[t], ib = idx[t + 1], ic = idx[t + 2];
        if (ia >= nv || ib >= nv || ic >= nv) continue;
        count[canon(ia, ib)]++;
        count[canon(ib, ic)]++;
        count[canon(ic, ia)]++;
    }
    std::map<u32, std::vector<u32>> adj;
    for (const auto& [e, n] : count) {
        if (n != 1) continue;
        adj[e.a].push_back(e.b);
        adj[e.b].push_back(e.a);
    }
    std::vector<WallPoint> walls;
    std::map<u32, bool> seen;
    for (const auto& [start, nbrs] : adj) {
        if (seen[start] || nbrs.empty()) continue;
        std::vector<u32> chain;
        u32 prev = u32(-1), cur = start;
        for (int guard = 0; guard < 100000; ++guard) {
            if (seen[cur]) break;
            seen[cur] = true;
            chain.push_back(cur);
            u32 next = u32(-1);
            for (u32 n : adj[cur]) {
                if (n != prev) {
                    next = n;
                    break;
                }
            }
            if (next == u32(-1) || seen[next]) break;
            prev = cur;
            cur = next;
        }
        if (chain.size() < 2) continue;
        u32 npts = u32(chain.size());
        for (size_t i = 0; i < chain.size(); ++i) {
            u32 vi = chain[i];
            WallPoint wp;
            wp.pos = {pos[vi * 3], pos[vi * 3 + 1], pos[vi * 3 + 2]};
            if (i == 0) wp.tag = npts;
            else if (i + 1 == chain.size()) wp.tag = u32(-int(npts));
            else wp.tag = 0;
            walls.push_back(wp);
        }
    }
    return walls;
}

std::vector<Checkpoint> checkpoints_from_mesh(const float* pos, size_t nv, int count) {
    if (nv == 0 || count < 2) return {};
    float minx = pos[0], maxx = pos[0], minz = pos[2], maxz = pos[2];
    for (size_t i = 0; i < nv; ++i) {
        minx = std::min(minx, pos[i * 3]);
        maxx = std::max(maxx, pos[i * 3]);
        minz = std::min(minz, pos[i * 3 + 2]);
        maxz = std::max(maxz, pos[i * 3 + 2]);
    }
    float dx = maxx - minx, dz = maxz - minz;
    bool along_x = dx >= dz;
    float length = along_x ? dx : dz;
    std::vector<Checkpoint> out;
    for (int i = 0; i < count; ++i) {
        float t = float(i) / float(count);
        Checkpoint c;
        c.distance = t * length;
        if (along_x) {
            float x = minx + t * dx;
            c.x0 = x;
            c.x1 = x;
            c.z0 = minz;
            c.z1 = maxz;
            c.dir_x = -1;
            c.dir_z = 0;
        } else {
            float z = minz + t * dz;
            c.z0 = z;
            c.z1 = z;
            c.x0 = minx;
            c.x1 = maxx;
            c.dir_x = 0;
            c.dir_z = -1;
        }
        out.push_back(c);
    }
    return out;
}

float estimate_length(const float* pos, size_t nv) {
    if (nv == 0) return 0;
    float minx = pos[0], maxx = pos[0], minz = pos[2], maxz = pos[2];
    for (size_t i = 0; i < nv; ++i) {
        minx = std::min(minx, pos[i * 3]);
        maxx = std::max(maxx, pos[i * 3]);
        minz = std::min(minz, pos[i * 3 + 2]);
        maxz = std::max(maxz, pos[i * 3 + 2]);
    }
    return std::max(maxx - minx, maxz - minz);
}

// Grid refs: (segment, triangle) pairs from all segments.
void write_spatial_grid(Bytes& out, const std::vector<SegMesh>& segs) {
    float minx = 0, maxx = 0, minz = 0, maxz = 0;
    bool any = false;
    for (const SegMesh& s : segs) {
        for (size_t i = 0; i < s.pos.size() / 3; ++i) {
            float x = s.pos[i * 3], z = s.pos[i * 3 + 2];
            if (!any) {
                minx = maxx = x;
                minz = maxz = z;
                any = true;
            } else {
                minx = std::min(minx, x);
                maxx = std::max(maxx, x);
                minz = std::min(minz, z);
                maxz = std::max(maxz, z);
            }
        }
    }
    if (!any) {
        w32(out, 0x48, 0);
        w32(out, 0x4C, 0);
        return;
    }

    float cell = 8.0f;
    minx = std::floor(minx / cell) * cell - cell;
    maxx = std::ceil(maxx / cell) * cell + cell;
    minz = std::floor(minz / cell) * cell - cell;
    maxz = std::ceil(maxz / cell) * cell + cell;
    int nx = std::max(2, int((maxx - minx) / cell) + 1);
    int nz = std::max(2, int((maxz - minz) / cell) + 1);
    while ((nx - 1) * (nz - 1) > 16000) {
        cell *= 2.f;
        nx = std::max(2, int((maxx - minx) / cell) + 1);
        nz = std::max(2, int((maxz - minz) / cell) + 1);
    }

    std::vector<float> xs(static_cast<size_t>(nx)), zs(static_cast<size_t>(nz));
    for (int i = 0; i < nx; ++i) xs[static_cast<size_t>(i)] = minx + (maxx - minx) * float(i) / float(nx - 1);
    for (int i = 0; i < nz; ++i) zs[static_cast<size_t>(i)] = minz + (maxz - minz) * float(i) / float(nz - 1);
    const int ncx = nx - 1, ncz = nz - 1;
    // per cell: list of (seg, tri)
    std::vector<std::vector<std::pair<u16, u16>>> buckets(static_cast<size_t>(ncx * ncz));
    const float x0 = xs[0], z0 = zs[0];
    const float xspan = std::max(1e-3f, xs[static_cast<size_t>(nx - 1)] - x0);
    const float zspan = std::max(1e-3f, zs[static_cast<size_t>(nz - 1)] - z0);

    auto cell_index = [&](float x, float z) {
        int ix = int((x - x0) / xspan * float(ncx));
        int iz = int((z - z0) / zspan * float(ncz));
        ix = std::clamp(ix, 0, ncx - 1);
        iz = std::clamp(iz, 0, ncz - 1);
        return iz * ncx + ix;
    };

    for (size_t si = 0; si < segs.size(); ++si) {
        const SegMesh& s = segs[si];
        const size_t nt = s.idx.size() / 3;
        for (size_t ti = 0; ti < nt; ++ti) {
            u16 ia = s.idx[ti * 3], ib = s.idx[ti * 3 + 1], ic = s.idx[ti * 3 + 2];
            float cx = (s.pos[ia * 3] + s.pos[ib * 3] + s.pos[ic * 3]) / 3.f;
            float cz = (s.pos[ia * 3 + 2] + s.pos[ib * 3 + 2] + s.pos[ic * 3 + 2]) / 3.f;
            auto& bucket = buckets[static_cast<size_t>(cell_index(cx, cz))];
            if (bucket.size() < 256) bucket.push_back({static_cast<u16>(si), static_cast<u16>(ti)});
        }
    }

    while (out.size() % 4) out.push_back(0);
    const u32 grid_hdr = static_cast<u32>(out.size());
    out.resize(grid_hdr + 8 + 4 * static_cast<size_t>(nx + nz));
    w16(out, grid_hdr + 4, static_cast<u16>(nx));
    w16(out, grid_hdr + 6, static_cast<u16>(nz));
    for (int i = 0; i < nx; ++i) wf(out, grid_hdr + 8 + 4 * static_cast<size_t>(i), xs[static_cast<size_t>(i)]);
    for (int i = 0; i < nz; ++i)
        wf(out, grid_hdr + 8 + 4 * static_cast<size_t>(nx + i), zs[static_cast<size_t>(i)]);

    while (out.size() % 4) out.push_back(0);
    const u32 cells_table = static_cast<u32>(out.size());
    out.resize(cells_table + 4 * static_cast<size_t>(ncx * ncz));

    for (int c = 0; c < ncx * ncz; ++c) {
        while (out.size() % 2) out.push_back(0);
        const u32 list_off = static_cast<u32>(out.size());
        w32(out, cells_table + 4 * static_cast<size_t>(c), list_off);
        // Group by segment for the {n, seg, tri[]} format
        std::map<u16, std::vector<u16>> by_seg;
        for (const auto& [seg, tri] : buckets[static_cast<size_t>(c)]) by_seg[seg].push_back(tri);
        for (auto& [seg, tris] : by_seg) {
            if (tris.size() > 512) tris.resize(512);
            const u16 n = static_cast<u16>(tris.size());
            const size_t base = out.size();
            out.resize(base + 4 + 2 * static_cast<size_t>(n));
            w16(out, base, n);
            w16(out, base + 2, seg);
            for (u16 k = 0; k < n; ++k) w16(out, base + 4 + 2 * static_cast<size_t>(k), tris[k]);
        }
        const size_t term = out.size();
        out.resize(term + 2);
        w16(out, term, 0);
    }
    w32(out, grid_hdr, cells_table);
    w32(out, 0x48, grid_hdr);
    w32(out, 0x4C, 0);
}

} // namespace

Bytes rebuild_gtrw_from_mesh(ByteSpan template_gtrw, const float* positions, size_t vertex_count,
                             const u32* indices, size_t index_count, const RoadRebuildOptions& opt) {
    if (vertex_count == 0 || index_count < 3 || index_count % 3 != 0)
        throw FormatError("rebuild-road: empty or non-triangle mesh");

    std::vector<SegMesh> segs = split_into_segments(positions, vertex_count, indices, index_count);
    Road tmpl = Road::parse(template_gtrw);

    const u32 nseg = static_cast<u32>(segs.size());
    const size_t seg_off = 0x60;
    // Layout: header | segment table | for each seg: verts then tris
    size_t cursor = seg_off + size_t(nseg) * 0x40;
    struct Loc {
        size_t voff, toff;
        u16 nv, nt;
    };
    std::vector<Loc> locs(nseg);
    for (u32 i = 0; i < nseg; ++i) {
        locs[i].voff = cursor;
        locs[i].nv = static_cast<u16>(segs[i].pos.size() / 3);
        cursor += size_t(locs[i].nv) * 16;
        locs[i].toff = cursor;
        locs[i].nt = static_cast<u16>(segs[i].idx.size() / 3);
        cursor += size_t(locs[i].nt) * 16;
    }

    Bytes out(cursor, 0);
    std::memcpy(out.data(), "GTRW", 4);
    w32(out, 0x10, rd32u(template_gtrw.data() + 0x10));
    w32(out, 0x14, tmpl.course_id);
    float length = opt.default_length > 0 ? opt.default_length : tmpl.length;
    if (length <= 0) length = estimate_length(positions, vertex_count);
    wf(out, 0x18, length);
    wf(out, 0x1C, tmpl.start_distance);
    w16(out, 0x20, tmpl.header_flag);

    w32(out, 0x30, nseg);
    w32(out, 0x34, static_cast<u32>(seg_off));

    for (u32 i = 0; i < nseg; ++i) {
        const size_t s = seg_off + size_t(i) * 0x40;
        w16(out, s + 0, locs[i].nv);
        w16(out, s + 2, locs[i].nt);
        w32(out, s + 4, static_cast<u32>(locs[i].voff));
        w32(out, s + 8, static_cast<u32>(locs[i].toff));
        w16(out, s + 0x16, 2);
        w16(out, s + 0x18, static_cast<u16>(i == 0 ? nseg - 1 : i - 1)); // prev
        w16(out, s + 0x1A, static_cast<u16>(i + 1 == nseg ? 0 : i + 1)); // next

        for (u16 vi = 0; vi < locs[i].nv; ++vi) {
            const size_t o = locs[i].voff + size_t(vi) * 16;
            wf(out, o + 0, segs[i].pos[size_t(vi) * 3 + 0]);
            wf(out, o + 4, segs[i].pos[size_t(vi) * 3 + 1]);
            wf(out, o + 8, segs[i].pos[size_t(vi) * 3 + 2]);
            w16(out, o + 12, 0xFFFF);
            w16(out, o + 14, 0xFFFF);
        }
        for (u16 ti = 0; ti < locs[i].nt; ++ti) {
            const size_t o = locs[i].toff + size_t(ti) * 16;
            w16(out, o + 0, segs[i].idx[size_t(ti) * 3 + 0]);
            w16(out, o + 2, segs[i].idx[size_t(ti) * 3 + 1]);
            w16(out, o + 4, segs[i].idx[size_t(ti) * 3 + 2]);
        }
    }

    auto append_table = [&](const void* data, size_t bytes, u32 count, size_t count_off, size_t ptr_off) {
        if (!count || !data || !bytes) {
            w32(out, count_off, 0);
            w32(out, ptr_off, 0);
            return;
        }
        while (out.size() % 4) out.push_back(0);
        const u32 off = static_cast<u32>(out.size());
        append_bytes(out, data, bytes);
        w32(out, count_off, count);
        w32(out, ptr_off, off);
    };

    if (opt.keep_template_markers && !tmpl.markers.empty()) {
        Bytes blob;
        for (const auto& m : tmpl.markers) {
            u32 flags = m.flags;
            float dist = m.distance;
            append_bytes(blob, &flags, 4);
            append_bytes(blob, &dist, 4);
        }
        append_table(blob.data(), blob.size(), static_cast<u32>(tmpl.markers.size()), 0x20, 0x24);
    } else {
        w32(out, 0x20, 0);
        w32(out, 0x24, 0);
    }

    if (opt.keep_template_grid_slots && !tmpl.grid.empty()) {
        Bytes blob;
        for (const auto& g : tmpl.grid) {
            float x = g.pos.x, y = g.pos.y, z = g.pos.z, yaw = g.yaw;
            append_bytes(blob, &x, 4);
            append_bytes(blob, &y, 4);
            append_bytes(blob, &z, 4);
            append_bytes(blob, &yaw, 4);
        }
        append_table(blob.data(), blob.size(), static_cast<u32>(tmpl.grid.size()), 0x28, 0x2C);
    } else {
        w32(out, 0x28, 0);
        w32(out, 0x2C, 0);
    }

    if (opt.keep_template_walls && !tmpl.wall_points.empty()) {
        Bytes blob;
        for (const auto& wpt : tmpl.wall_points) {
            float x = wpt.pos.x, y = wpt.pos.y, z = wpt.pos.z;
            u32 tag = wpt.tag;
            append_bytes(blob, &x, 4);
            append_bytes(blob, &y, 4);
            append_bytes(blob, &z, 4);
            append_bytes(blob, &tag, 4);
        }
        append_table(blob.data(), blob.size(), static_cast<u32>(tmpl.wall_points.size()), 0x38, 0x3C);
    } else if (opt.generate_walls_from_boundary) {
        auto gen = walls_from_boundary(positions, vertex_count, indices, index_count);
        Bytes blob;
        for (const auto& wpt : gen) {
            float x = wpt.pos.x, y = wpt.pos.y, z = wpt.pos.z;
            u32 tag = wpt.tag;
            append_bytes(blob, &x, 4);
            append_bytes(blob, &y, 4);
            append_bytes(blob, &z, 4);
            append_bytes(blob, &tag, 4);
        }
        append_table(blob.data(), blob.size(), static_cast<u32>(gen.size()), 0x38, 0x3C);
    } else {
        w32(out, 0x38, 0);
        w32(out, 0x3C, 0);
    }

    if (opt.keep_template_checkpoints && !tmpl.checkpoints.empty()) {
        Bytes blob;
        for (const auto& c : tmpl.checkpoints) {
            float vals[8] = {c.x0, c.z0, c.x1, c.z1, c.distance, c.dir_x, c.dir_z, c.unknown};
            append_bytes(blob, vals, sizeof(vals));
        }
        append_table(blob.data(), blob.size(), static_cast<u32>(tmpl.checkpoints.size()), 0x40, 0x44);
    } else if (opt.generate_checkpoints) {
        auto cps = checkpoints_from_mesh(positions, vertex_count, opt.checkpoint_count);
        Bytes blob;
        for (const auto& c : cps) {
            float vals[8] = {c.x0, c.z0, c.x1, c.z1, c.distance, c.dir_x, c.dir_z, c.unknown};
            append_bytes(blob, vals, sizeof(vals));
        }
        append_table(blob.data(), blob.size(), static_cast<u32>(cps.size()), 0x40, 0x44);
    } else {
        w32(out, 0x40, 0);
        w32(out, 0x44, 0);
    }

    write_spatial_grid(out, segs);

    w32(out, 0x50, 0);
    w32(out, 0x54, 0);
    w32(out, 0x58, 0);
    w32(out, 0x5C, static_cast<u32>(out.size()));
    w32(out, 0x08, static_cast<u32>(out.size()));

    Road::parse(out);
    return out;
}

Bytes rebuild_course_road_from_glb(ByteSpan original_course, ByteSpan glb, const RoadRebuildOptions& opt) {
    CourseFile file = CourseFile::parse(original_course);
    const CourseSection* road_sec = file.find(kSlotRoad);
    if (!road_sec) throw FormatError("course has no GTRW road section");

    scene::Model model = load_glb(glb, {}, "road_rebuild");
    std::vector<float> pos;
    std::vector<u32> idx;
    for (const scene::Mesh& mesh : model.meshes) {
        u32 base = static_cast<u32>(pos.size() / 3);
        for (const scene::Vertex& v : mesh.vertices) {
            pos.push_back(v.pos[0]);
            pos.push_back(v.pos[1]);
            pos.push_back(v.pos[2]);
        }
        if (!mesh.indices.empty()) {
            for (size_t i = 0; i + 2 < mesh.indices.size(); i += 3) {
                idx.push_back(base + mesh.indices[i]);
                idx.push_back(base + mesh.indices[i + 1]);
                idx.push_back(base + mesh.indices[i + 2]);
            }
        } else {
            for (u32 i = 0; i + 2 < static_cast<u32>(mesh.vertices.size()); i += 3) {
                idx.push_back(base + i);
                idx.push_back(base + i + 1);
                idx.push_back(base + i + 2);
            }
        }
    }
    if (pos.empty() || idx.empty()) throw FormatError("GLB has no triangle mesh");

    ByteSpan old_gtrw = original_course.subspan(road_sec->offset, road_sec->size);
    Bytes new_gtrw =
        rebuild_gtrw_from_mesh(old_gtrw, pos.data(), pos.size() / 3, idx.data(), idx.size(), opt);

    std::vector<Bytes> payloads(static_cast<size_t>(kSlotCount));
    for (const CourseSection& s : file.sections()) {
        Bytes chunk(s.size);
        std::memcpy(chunk.data(), original_course.data() + s.offset, s.size);
        payloads[static_cast<size_t>(s.slot)] = std::move(chunk);
    }
    payloads[static_cast<size_t>(kSlotRoad)] = std::move(new_gtrw);

    Bytes table(static_cast<size_t>(kSlotCount) * 4, 0);
    Bytes body;
    u32 cursor = static_cast<u32>(kSlotCount * 4);
    for (int slot = 0; slot < kSlotCount; ++slot) {
        if (payloads[static_cast<size_t>(slot)].empty()) continue;
        std::memcpy(table.data() + slot * 4, &cursor, 4);
        body.insert(body.end(), payloads[static_cast<size_t>(slot)].begin(),
                    payloads[static_cast<size_t>(slot)].end());
        cursor += static_cast<u32>(payloads[static_cast<size_t>(slot)].size());
    }
    Bytes raw;
    raw.insert(raw.end(), table.begin(), table.end());
    raw.insert(raw.end(), body.begin(), body.end());
    CourseFile::parse(raw);
    return raw;
}

std::string rebuild_course_road_files(const std::string& original_path, const std::string& glb_path,
                                      const std::string& out_path, const RoadRebuildOptions& opt) {
    Bytes course = load_course_bytes(original_path);
    auto glb = read_host_file(glb_path);
    if (!glb) throw FormatError("cannot read " + glb_path);
    Bytes packed = rebuild_course_road_from_glb(course, *glb, opt);
    save_course_bytes(out_path, packed, false);
    std::ostringstream msg;
    msg << "rebuild-road " << glb_path << " -> " << out_path << " (" << packed.size() << " bytes raw)";
    return msg.str();
}

} // namespace gt3r::course
