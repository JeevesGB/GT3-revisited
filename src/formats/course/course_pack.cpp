#include "formats/course/course_pack.h"

#include "base/file.h"
#include "base/gzip.h"
#include "formats/course/road.h"

#include <algorithm>
#include <cstdio>
#include <cstring>
#include <filesystem>
#include <sstream>

namespace fs = std::filesystem;

namespace gt3r::course {
namespace {

bool looks_gzip(ByteSpan d) { return d.size() >= 2 && d[0] == 0x1f && d[1] == 0x8b; }

std::string json_escape(const std::string& s) {
    std::string o;
    o.reserve(s.size() + 8);
    for (char c : s) {
        if (c == '\\' || c == '"') o.push_back('\\');
        o.push_back(c);
    }
    return o;
}

void write_text(const fs::path& p, const std::string& t) {
    fs::create_directories(p.parent_path());
    if (!write_host_file(p.string(), ByteSpan{reinterpret_cast<const u8*>(t.data()), t.size()}))
        throw FormatError("failed to write " + p.string());
}

} // namespace

Bytes load_course_bytes(const std::string& path) {
    auto raw = read_host_file(path);
    if (!raw) throw FormatError("cannot read " + path);
    if (looks_gzip(*raw)) return inflate_gzip_auto(*raw);
    return *raw;
}

void save_course_bytes(const std::string& path, ByteSpan raw, bool force_gzip) {
    bool gz = force_gzip;
    if (path.size() >= 3 && (path.ends_with(".gz") || path.ends_with(".GZ"))) gz = true;
    Bytes out = gz ? deflate_gzip(raw) : Bytes(raw.begin(), raw.end());
    fs::create_directories(fs::path(path).parent_path());
    if (!write_host_file(path, out)) throw FormatError("cannot write " + path);
}

std::string unpack_course(const std::string& src_path, const std::string& out_dir) {
    Bytes data = load_course_bytes(src_path);
    CourseFile file = CourseFile::parse(data);
    fs::path root(out_dir);
    fs::create_directories(root / "blobs");

    std::ostringstream man;
    man << "{\n  \"source\": \"" << json_escape(src_path) << "\",\n"
        << "  \"size\": " << data.size() << ",\n"
        << "  \"format\": \"gt3-course-v2\",\n"
        << "  \"gzip\": " << (looks_gzip(*read_host_file(src_path)) ? "true" : "false") << ",\n"
        << "  \"slots\": [\n";

    std::ostringstream lock;
    lock << "{\n  \"format\": \"gt3-structure-lock-v1\",\n  \"total_raw\": " << data.size()
         << ",\n  \"slot_sizes\": {\n";

    const auto& secs = file.sections();
    for (size_t i = 0; i < secs.size(); ++i) {
        const auto& s = secs[i];
        ByteSpan span = file.section(data, s.slot);
        std::string tag = s.tag.empty() ? std::string("bin") : s.tag;
        char name[64];
        std::snprintf(name, sizeof(name), "slot_%02d_%s.bin", s.slot, tag.c_str());
        fs::path blob = root / "blobs" / name;
        if (!write_host_file(blob.string(), span)) throw FormatError("write blob failed");

        if (s.slot == kSlotRoad && span.size() >= 4) {
            fs::create_directories(root / "road");
            write_host_file((root / "road" / "GTRW.bin").string(), span);
        }

        man << "    {\"slot\": " << s.slot << ", \"tag\": \"" << json_escape(s.tag)
            << "\", \"size\": " << s.size << ", \"blob\": \"blobs/" << name << "\"}";
        lock << "    \"" << s.slot << "\": " << s.size;
        if (i + 1 < secs.size()) {
            man << ",\n";
            lock << ",\n";
        } else {
            man << "\n";
            lock << "\n";
        }
    }
    man << "  ]\n}\n";
    lock << "  }\n}\n";
    write_text(root / "manifest.json", man.str());
    write_text(root / "structure_lock.json", lock.str());

    std::ostringstream msg;
    msg << "unpacked " << secs.size() << " sections -> " << out_dir;
    return msg.str();
}

std::string pack_course(const std::string& work_dir, const std::string& out_path) {
    fs::path root(work_dir);
    auto man_bytes = read_host_file((root / "manifest.json").string());
    if (!man_bytes) throw FormatError("manifest.json missing — unpack a course first");

    // Minimal JSON scan for "slot": N and "blob": "..."
    std::string man(reinterpret_cast<const char*>(man_bytes->data()), man_bytes->size());
    struct Entry {
        int slot = 0;
        std::string blob;
        size_t size = 0;
    };
    std::vector<Entry> entries;
    size_t pos = 0;
    while (pos < man.size()) {
        size_t s = man.find("\"slot\"", pos);
        if (s == std::string::npos) break;
        size_t colon = man.find(':', s);
        int slot = std::atoi(man.c_str() + colon + 1);
        size_t b = man.find("\"blob\"", s);
        if (b == std::string::npos || b > s + 200) {
            pos = s + 5;
            continue;
        }
        size_t q0 = man.find('"', man.find(':', b) + 1);
        size_t q1 = man.find('"', q0 + 1);
        std::string blob = man.substr(q0 + 1, q1 - q0 - 1);
        entries.push_back({slot, blob, 0});
        pos = q1 + 1;
    }
    if (entries.empty()) throw FormatError("manifest has no slots");

    auto lock_bytes = read_host_file((root / "structure_lock.json").string());
    std::vector<size_t> lock_sizes(kSlotCount, 0);
    bool have_lock = false;
    if (lock_bytes) {
        have_lock = true;
        std::string lock(reinterpret_cast<const char*>(lock_bytes->data()), lock_bytes->size());
        for (int slot = 0; slot < kSlotCount; ++slot) {
            char key[16];
            std::snprintf(key, sizeof(key), "\"%d\"", slot);
            size_t k = lock.find(key);
            if (k == std::string::npos) continue;
            size_t c = lock.find(':', k);
            lock_sizes[size_t(slot)] = size_t(std::atoll(lock.c_str() + c + 1));
        }
    }

    std::vector<Bytes> payloads(kSlotCount);
    for (auto& e : entries) {
        fs::path blob_path = root / e.blob;
        // Prefer edited road binary
        if (e.slot == kSlotRoad) {
            auto g = read_host_file((root / "road" / "GTRW.bin").string());
            if (g) {
                payloads[size_t(e.slot)] = *g;
                e.size = g->size();
                continue;
            }
        }
        auto b = read_host_file(blob_path.string());
        if (!b) throw FormatError("missing blob " + blob_path.string());
        payloads[size_t(e.slot)] = *b;
        e.size = b->size();
        if (have_lock && lock_sizes[size_t(e.slot)] && lock_sizes[size_t(e.slot)] != e.size) {
            throw FormatError("slot " + std::to_string(e.slot) + " size changed (structure-safe pack)");
        }
    }

    Bytes table(size_t(kSlotCount) * 4, 0);
    Bytes body;
    u32 cursor = u32(kSlotCount * 4);
    for (int slot = 0; slot < kSlotCount; ++slot) {
        if (payloads[size_t(slot)].empty()) continue;
        std::memcpy(table.data() + slot * 4, &cursor, 4);
        body.insert(body.end(), payloads[size_t(slot)].begin(), payloads[size_t(slot)].end());
        cursor += u32(payloads[size_t(slot)].size());
    }
    Bytes raw;
    raw.insert(raw.end(), table.begin(), table.end());
    raw.insert(raw.end(), body.begin(), body.end());

    // Validate parse
    CourseFile::parse(raw);
    save_course_bytes(out_path, raw, false);

    std::ostringstream msg;
    msg << "packed " << entries.size() << " sections -> " << out_path << " (" << raw.size() << " bytes raw)";
    return msg.str();
}

std::string export_road_gltf(const std::string& gtrw_or_work, const std::string& out_gltf, bool z_up) {
    fs::path p(gtrw_or_work);
    fs::path gtrw = p;
    if (fs::is_directory(p)) gtrw = p / "road" / "GTRW.bin";
    auto bytes = read_host_file(gtrw.string());
    if (!bytes) throw FormatError("missing GTRW at " + gtrw.string());
    Road road = Road::parse(*bytes);

    std::vector<float> pos;
    std::vector<u32> indices;
    u32 base = 0;
    for (const RoadSegment& seg : road.segments) {
        for (const Vec3& v : seg.vertices) {
            if (z_up) {
                pos.push_back(v.x);
                pos.push_back(-v.z);
                pos.push_back(v.y);
            } else {
                pos.push_back(v.x);
                pos.push_back(v.y);
                pos.push_back(v.z);
            }
        }
        for (const RoadTriangle& t : seg.triangles) {
            indices.push_back(base + t.a);
            indices.push_back(base + t.b);
            indices.push_back(base + t.c);
        }
        base += u32(seg.vertices.size());
    }

    Bytes bin;
    auto append = [&](const void* d, size_t n) {
        const u8* p = static_cast<const u8*>(d);
        bin.insert(bin.end(), p, p + n);
    };
    size_t pos_off = 0;
    append(pos.data(), pos.size() * sizeof(float));
    size_t idx_off = bin.size();
    // align 4
    while (bin.size() % 4) bin.push_back(0);
    idx_off = bin.size();
    append(indices.data(), indices.size() * sizeof(u32));

    fs::path gltf_path(out_gltf);
    fs::path bin_path = gltf_path;
    bin_path.replace_extension(".bin");
    fs::create_directories(gltf_path.parent_path());
    write_host_file(bin_path.string(), bin);

    std::ostringstream json;
    json << "{\n"
         << "  \"asset\": {\"version\": \"2.0\", \"generator\": \"GT3R course_pack\"},\n"
         << "  \"scene\": 0,\n"
         << "  \"scenes\": [{\"nodes\": [0]}],\n"
         << "  \"nodes\": [{\"mesh\": 0, \"name\": \"gt3_road\"}],\n"
         << "  \"meshes\": [{\"primitives\": [{\"attributes\": {\"POSITION\": 0}, \"indices\": 1}]}],\n"
         << "  \"buffers\": [{\"uri\": \"" << bin_path.filename().string() << "\", \"byteLength\": " << bin.size()
         << "}],\n"
         << "  \"bufferViews\": [\n"
         << "    {\"buffer\": 0, \"byteOffset\": " << pos_off << ", \"byteLength\": " << (pos.size() * 4)
         << ", \"target\": 34962},\n"
         << "    {\"buffer\": 0, \"byteOffset\": " << idx_off << ", \"byteLength\": " << (indices.size() * 4)
         << ", \"target\": 34963}\n"
         << "  ],\n"
         << "  \"accessors\": [\n"
         << "    {\"bufferView\": 0, \"componentType\": 5126, \"count\": " << (pos.size() / 3)
         << ", \"type\": \"VEC3\"},\n"
         << "    {\"bufferView\": 1, \"componentType\": 5125, \"count\": " << indices.size()
         << ", \"type\": \"SCALAR\"}\n"
         << "  ]\n"
         << "}\n";
    write_text(gltf_path, json.str());

    std::ostringstream msg;
    msg << "road glTF -> " << out_gltf << " (verts=" << (pos.size() / 3) << " tris=" << (indices.size() / 3) << ")";
    return msg.str();
}

} // namespace gt3r::course
